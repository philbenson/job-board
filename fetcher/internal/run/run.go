// Package run fetches each configured board in turn, stores it and records
// the attempt.
package run

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"time"

	"github.com/jackc/pgx/v5/pgconn"

	"github.com/philbenson/job-board/fetcher/internal/greenhouse"
	"github.com/philbenson/job-board/fetcher/internal/store"
)

// The failure codes recorded in fetch_runs.failure: short and fixed, never an
// error's text, which can carry a URL or a server's message. The log line
// adds a safe detail beside some of them; see detail.
const (
	FailureRequest        = "request"         // the request failed or timed out
	FailureStatus         = "status"          // the board answered with a status other than 200
	FailureTooLarge       = "too-large"       // the answer was over the size cap
	FailureDecode         = "decode"          // the answer was not the feed's JSON
	FailureInvalidPosting = "invalid-posting" // a posting failed a check
	FailureDatabase       = "database"        // the board could not be stored
	FailureInterrupted    = "interrupted"     // the run was interrupted while the board was fetched or written
	FailureLocked         = "locked"          // another run was fetching the board, so this one did not
)

// Long enough to reconnect and insert one row on a healthy database. The
// record has a context of its own, cut loose from the run's, so it is written
// after an interrupt too, through a new connection if the old one closed; this
// bounds how long the interrupt waits.
const recordTimeout = 5 * time.Second

// Runner fetches boards from Feed into Store and logs one line per board.
type Runner struct {
	Feed  *greenhouse.Client
	Store *store.Store
	Log   *slog.Logger
}

// Boards fetches every board in turn and reports whether all of them
// succeeded.
//
// Invariant: one board failing never stops another, and a dropped database
// connection fails at most the board in hand. Each board is written whole or
// not at all, and each attempt is recorded in fetch_runs whether it succeeded
// or not. Once ctx ends, the board in hand rolls back and is recorded as
// failed with the code interrupted, and no further board is started.
func (r *Runner) Boards(ctx context.Context, boards []string) bool {
	allSucceeded := true
	for _, board := range boards {
		if ctx.Err() != nil {
			r.Log.Warn("board not fetched", "board", board, "outcome", "skipped", "reason", "interrupted")
			allSucceeded = false
			continue
		}
		if !r.board(ctx, board) {
			allSucceeded = false
		}
	}
	return allSucceeded
}

// board fetches, stores and records one board, and reports whether all three
// succeeded.
func (r *Runner) board(ctx context.Context, board string) bool {
	record := store.Run{Source: greenhouse.Source, Board: board, StartedAt: time.Now(), Outcome: store.Succeeded}
	lock, err := r.Store.LockBoard(ctx, greenhouse.Source, board)
	if err == nil {
		record.Counts, err = r.fetchAndWrite(ctx, lock, board)
	}
	if err != nil {
		record.Outcome, record.Failure = store.Failed, failure(ctx, err)
	}
	record.FinishedAt = time.Now()

	// Recorded even when ctx has ended, so an interrupted board leaves its trace.
	recordCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), recordTimeout)
	defer cancel()
	recorded := r.Store.RecordRun(recordCtx, record) == nil
	if lock != nil {
		// Released after the record. Should the release fail, the lock is held
		// only until the process exits and its session ends, and no run visits
		// a board twice.
		_ = r.Store.Unlock(recordCtx, lock)
	}

	attributes := []any{"board", board, "outcome", record.Outcome}
	if record.Outcome == store.Succeeded {
		attributes = append(attributes, "seen", record.Counts.Seen, "new", record.Counts.New, "closed", record.Counts.Closed)
	} else {
		attributes = append(attributes, "failure", record.Failure)
		attributes = append(attributes, detail(record.Failure, err)...)
	}
	if !recorded {
		attributes = append(attributes, "recorded", false)
	}
	level := slog.LevelInfo
	switch {
	case !recorded:
		level = slog.LevelError
	case record.Failure == FailureLocked: // expected while another run is going, but still a board not fetched
		level = slog.LevelWarn
	case record.Outcome == store.Failed:
		level = slog.LevelError
	}
	r.Log.Log(ctx, level, "board fetched", attributes...)
	return record.Outcome == store.Succeeded && recorded
}

// fetchAndWrite fetches one board and stores it while holding its lock. A
// connection that closes after the lock was taken takes the lock with it and
// fails the board.
func (r *Runner) fetchAndWrite(ctx context.Context, lock *store.BoardLock, board string) (store.Counts, error) {
	postings, err := r.Feed.Fetch(ctx, board)
	if err != nil {
		return store.Counts{}, err
	}
	return r.Store.WriteBoard(ctx, lock, postings)
}

// detail is what the log says beside a failure code to help act on it: the
// status a board answered, the posting and the check it failed, the
// PostgreSQL condition code, or whether a request timed out. None of it is a
// URL, a server's text or a posting's text, which an error's message can
// carry, and fetch_runs keeps the code alone.
func detail(code string, err error) []any {
	var status *greenhouse.StatusError
	var invalid *greenhouse.InvalidPostingError
	var refused *pgconn.PgError
	var network net.Error
	switch {
	case code == FailureStatus && errors.As(err, &status):
		return []any{"http_status", status.Code}
	case code == FailureInvalidPosting && errors.As(err, &invalid):
		return []any{"posting", invalid.ID, "check", invalid.Check}
	case code == FailureDatabase && errors.As(err, &refused):
		return []any{"condition", refused.Code}
	case code == FailureRequest:
		timedOut := errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &network) && network.Timeout())
		return []any{"timed_out", timedOut}
	}
	return nil
}

// failure is the failure code for an error from fetching or storing a board.
// Once the run's context has ended, the cause is the interrupt, whatever the
// error that followed from it.
func failure(ctx context.Context, err error) string {
	switch {
	case ctx.Err() != nil:
		return FailureInterrupted
	case errors.Is(err, store.ErrLocked):
		return FailureLocked
	case errors.Is(err, greenhouse.ErrRequest):
		return FailureRequest
	case errors.Is(err, greenhouse.ErrStatus):
		return FailureStatus
	case errors.Is(err, greenhouse.ErrTooLarge):
		return FailureTooLarge
	case errors.Is(err, greenhouse.ErrDecode):
		return FailureDecode
	case errors.Is(err, greenhouse.ErrInvalidPosting):
		return FailureInvalidPosting
	default: // every error the feed returns is one of the above, so this one came from the database
		return FailureDatabase
	}
}

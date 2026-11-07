// Package store writes fetched postings and the record of each fetch to
// PostgreSQL. The tables are the backend's migrations' to create and change;
// this package only reads and writes rows.
package store

import (
	"cmp"
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/philbenson/job-board/fetcher/internal/posting"
)

const connectTimeout = 5 * time.Second // a database that is down stops the run promptly instead of hanging it

// Store is one connection, used by one board at a time, and replaced by a new
// one when it closes.
type Store struct {
	config *pgx.ConnConfig
	conn   *pgx.Conn
}

// Connect opens the connection and checks the database answers.
func Connect(ctx context.Context, databaseURL string) (*Store, error) {
	config, err := pgx.ParseConfig(databaseURL)
	if err != nil {
		return nil, err
	}
	config.ConnectTimeout = cmp.Or(config.ConnectTimeout, connectTimeout)
	conn, err := pgx.ConnectConfig(ctx, config)
	if err != nil {
		return nil, err
	}
	return &Store{config: config, conn: conn}, nil
}

// reconnect opens a new connection when the current one has closed, as it
// does when the database ends the session or a statement is interrupted, so
// one dropped connection fails at most the board in hand.
func (s *Store) reconnect(ctx context.Context) error {
	if !s.conn.IsClosed() {
		return nil
	}
	conn, err := pgx.ConnectConfig(ctx, s.config)
	if err != nil {
		return err
	}
	s.conn = conn
	return nil
}

func (s *Store) Close(ctx context.Context) error {
	return s.conn.Close(ctx)
}

// boardLockClass is the first key of every board lock the fetcher takes,
// naming the fetcher among the users of PostgreSQL's advisory locks; the second
// key is a hash of the source and board. Two-key locks never collide with
// one-key ones, which the rest of the system is free to use. Its bytes spell
// "FETC".
const boardLockClass int32 = 0x46455443

// ErrLocked: another session holds the board's lock, so another run is
// fetching it.
var ErrLocked = errors.New("another run holds the board's lock")

// errLockLost: the connection that took the board's lock has closed, and the
// lock went with it.
var errLockLost = errors.New("the connection holding the board's lock has closed")

// BoardLock is one board's advisory lock, held by the session that took it.
type BoardLock struct {
	conn          *pgx.Conn
	source, board string
}

// LockBoard takes a board's lock without waiting, reconnecting first if the
// connection has closed. It returns ErrLocked when another session holds the
// lock.
//
// Invariant: a board is fetched and written by at most one run at a time.
// The lock is taken before the fetch, so two runs cannot store their feeds in
// an order other than the one they read them in.
func (s *Store) LockBoard(ctx context.Context, source, board string) (*BoardLock, error) {
	if err := s.reconnect(ctx); err != nil {
		return nil, err
	}
	var locked bool
	if err := s.conn.QueryRow(ctx, "SELECT pg_try_advisory_lock($1::int4, "+boardLockKey+")",
		boardLockClass, source, board).Scan(&locked); err != nil {
		return nil, err
	}
	if !locked {
		return nil, ErrLocked
	}
	return &BoardLock{conn: s.conn, source: source, board: board}, nil
}

// boardLockKey is the lock's second key, computed in SQL from the source ($2)
// and the board ($3).
const boardLockKey = "hashtext($2::text || ':' || $3::text)"

// Unlock releases a board's lock. A lock whose connection has closed went with
// its session, so there is nothing to release then.
func (s *Store) Unlock(ctx context.Context, lock *BoardLock) error {
	if lock.conn.IsClosed() {
		return nil
	}
	_, err := lock.conn.Exec(ctx, "SELECT pg_advisory_unlock($1::int4, "+boardLockKey+")",
		boardLockClass, lock.source, lock.board)
	return err
}

// Counts is what one write of a board did: postings in the feed, postings
// stored for the first time, and open postings closed because the feed no
// longer lists them. A posting reopened is seen, not new.
type Counts struct {
	Seen, New, Closed int
}

// Every timestamp below is now(), the transaction's start time, so one write
// stamps all its rows alike and a row's first_seen_at or last_seen_at equal to
// now() marks it as inserted or seen by this write.
const (
	upsertPosting = `
		INSERT INTO postings (source, board, external_id, title, company_name, location, url,
		                      content_html, first_published_at, source_updated_at, first_seen_at, last_seen_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now(), now())
		ON CONFLICT (source, board, external_id) DO UPDATE SET
			title = excluded.title,
			company_name = excluded.company_name,
			location = excluded.location,
			url = excluded.url,
			content_html = excluded.content_html,
			first_published_at = excluded.first_published_at,
			source_updated_at = excluded.source_updated_at,
			last_seen_at = excluded.last_seen_at,
			closed_at = NULL`
	countWritten = `
		SELECT count(*) FILTER (WHERE last_seen_at = now()), count(*) FILTER (WHERE first_seen_at = now())
		FROM postings WHERE source = $1 AND board = $2`
	closeUnseen = `
		UPDATE postings SET closed_at = now()
		WHERE source = $1 AND board = $2 AND closed_at IS NULL AND last_seen_at <> now()`
)

// WriteBoard stores a board's whole feed in one transaction: every posting is
// inserted or brought up to date and marked open, and every open posting of
// the board the feed no longer lists is closed.
//
// Invariant: each board is written whole or not at all. Any failure, or ctx
// ending, rolls the whole write back.
//
// It writes only through the connection that holds the board's lock, and
// never reconnects: once that connection has closed, the lock is gone and the
// write fails.
//
// Invariant: writing the same feed again adds no row and changes nothing but
// last_seen_at.
func (s *Store) WriteBoard(ctx context.Context, lock *BoardLock, postings []posting.Posting) (Counts, error) {
	if lock.conn != s.conn || lock.conn.IsClosed() {
		return Counts{}, errLockLost
	}
	source, board := lock.source, lock.board
	var counts Counts
	err := pgx.BeginFunc(ctx, lock.conn, func(tx pgx.Tx) error {
		batch := &pgx.Batch{}
		for _, p := range postings {
			batch.Queue(upsertPosting, source, board, p.ExternalID, p.Title, nullIfEmpty(p.CompanyName),
				nullIfEmpty(p.Location), p.URL, nullIfEmpty(p.ContentHTML), p.FirstPublishedAt, p.SourceUpdatedAt)
		}
		if err := tx.SendBatch(ctx, batch).Close(); err != nil {
			return err
		}
		if err := tx.QueryRow(ctx, countWritten, source, board).Scan(&counts.Seen, &counts.New); err != nil {
			return err
		}
		closed, err := tx.Exec(ctx, closeUnseen, source, board)
		if err != nil {
			return err
		}
		counts.Closed = int(closed.RowsAffected())
		return nil
	})
	if err != nil {
		return Counts{}, err
	}
	return counts, nil
}

// Outcome is how a fetch of one board ended.
type Outcome string

const (
	Succeeded Outcome = "succeeded"
	Failed    Outcome = "failed"
)

// Run is the record of one attempt to fetch one board.
type Run struct {
	Source, Board         string
	StartedAt, FinishedAt time.Time
	Outcome               Outcome
	Counts                Counts
	Failure               string // a short code naming what failed; empty when the run succeeded
}

// RecordRun writes one fetch_runs row, in its own statement, so a failed
// board's record survives that board's rolled-back write. It reconnects
// first if the connection has closed, so a write that lost its connection is
// still recorded.
func (s *Store) RecordRun(ctx context.Context, run Run) error {
	if err := s.reconnect(ctx); err != nil {
		return err
	}
	_, err := s.conn.Exec(ctx, `
		INSERT INTO fetch_runs (source, board, started_at, finished_at, outcome,
		                        postings_seen, postings_new, postings_closed, failure)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		run.Source, run.Board, run.StartedAt, run.FinishedAt, string(run.Outcome),
		run.Counts.Seen, run.Counts.New, run.Counts.Closed, nullIfEmpty(run.Failure))
	return err
}

// nullIfEmpty stores an absent optional text as NULL rather than as an empty string.
func nullIfEmpty(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}

// Command fetcher reads the configured Greenhouse boards once into PostgreSQL
// and exits.
//
// It exits 0 when every board was fetched and stored, 1 when any board
// failed, and 2 when its settings are refused, the database cannot be
// reached, or it is not migrated, before any board is tried.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgconn"

	"github.com/philbenson/job-board/fetcher/internal/greenhouse"
	"github.com/philbenson/job-board/fetcher/internal/run"
	"github.com/philbenson/job-board/fetcher/internal/settings"
	"github.com/philbenson/job-board/fetcher/internal/store"
)

const (
	exitSucceeded   = 0
	exitBoardFailed = 1
	exitCannotStart = 2
)

func main() {
	// An interrupt cancels the context, so the board in hand rolls back.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	code := execute(ctx, os.Getenv, os.Stderr, &greenhouse.Client{})
	stop()
	os.Exit(code)
}

// execute is the whole command, with its surroundings passed in so tests can
// give it their own environment, standard error and feed.
func execute(ctx context.Context, getenv func(string) string, stderr io.Writer, feed *greenhouse.Client) int {
	config, err := settings.Load(getenv)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return exitCannotStart
	}
	db, err := store.Connect(ctx, config.DatabaseURL)
	if err != nil {
		fmt.Fprintln(stderr, connectProblem(err))
		return exitCannotStart
	}
	defer db.Close(context.WithoutCancel(ctx))
	if err := db.CheckMigrated(ctx); err != nil {
		if errors.Is(err, store.ErrNotMigrated) {
			fmt.Fprintln(stderr, "the database DATABASE_URL names is not migrated: "+
				"run `uv run alembic upgrade head` in backend/")
		} else {
			fmt.Fprintln(stderr, "could not check the database DATABASE_URL names is migrated"+condition(err))
		}
		return exitCannotStart
	}

	runner := &run.Runner{Feed: feed, Store: db, Log: slog.New(slog.NewTextHandler(stderr, nil))}
	if !runner.Boards(ctx, config.Boards) {
		return exitBoardFailed
	}
	return exitSucceeded
}

// connectProblem says why the connection failed. The driver's message names
// the server and user, so it is never printed: a server that answered gives
// its PostgreSQL condition code, and one that did not is most likely not
// running.
func connectProblem(err error) string {
	var refused *pgconn.PgError
	if !errors.As(err, &refused) {
		return "could not reach the database DATABASE_URL names; " +
			"for the local one, start it from the repository root with: docker compose up -d --wait db"
	}
	switch refused.Code {
	case "28P01", "28000": // invalid_password, invalid_authorization_specification
		return "the database server refused the user name or password in DATABASE_URL" + condition(err)
	case "3D000": // invalid_catalog_name
		return "the database DATABASE_URL names does not exist" + condition(err)
	default:
		return "the database server refused the connection" + condition(err)
	}
}

// condition is the PostgreSQL condition code an error carries, in words to
// end a message with, or nothing when it carries none.
func condition(err error) string {
	var refused *pgconn.PgError
	if errors.As(err, &refused) {
		return " (PostgreSQL condition " + refused.Code + ")"
	}
	return ""
}

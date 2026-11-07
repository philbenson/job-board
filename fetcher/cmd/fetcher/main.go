// Command fetcher reads the configured Greenhouse boards once into PostgreSQL
// and exits.
//
// It exits 0 when every board was fetched and stored, 1 when any board
// failed, and 2 when its settings are refused or the database cannot be
// reached at all, before any board is tried.
package main

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

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
		// The driver's message names the server and user; the setting is enough to go on.
		fmt.Fprintln(stderr, "could not connect to the database DATABASE_URL names; "+
			"for the local one, start it from the repository root with: docker compose up -d --wait db")
		return exitCannotStart
	}
	defer db.Close(context.WithoutCancel(ctx))

	runner := &run.Runner{Feed: feed, Store: db, Log: slog.New(slog.NewTextHandler(stderr, nil))}
	if !runner.Boards(ctx, config.Boards) {
		return exitBoardFailed
	}
	return exitSucceeded
}

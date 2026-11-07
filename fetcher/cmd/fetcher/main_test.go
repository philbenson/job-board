package main

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"

	"github.com/philbenson/job-board/fetcher/internal/greenhouse"
	"github.com/philbenson/job-board/fetcher/internal/testdb"
)

func TestMain(m *testing.M) {
	testdb.Main(m)
}

// feed serves the fixture for every board but "larkspur", which answers 502.
func feed(t *testing.T) *greenhouse.Client {
	t.Helper()
	fixture, err := os.ReadFile("../../internal/greenhouse/testdata/board.json")
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/larkspur/") {
			http.Error(w, "oops", http.StatusBadGateway)
			return
		}
		_, _ = w.Write(fixture)
	}))
	t.Cleanup(server.Close)
	t.Cleanup(func() { emptyTables(t) })
	return &greenhouse.Client{BaseURL: server.URL}
}

func emptyTables(t *testing.T) {
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	if _, err := conn.Exec(ctx, "TRUNCATE postings, fetch_runs CASCADE"); err != nil {
		t.Error(err)
	}
}

func environment(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

func TestExitsZeroWhenEveryBoardSucceeds(t *testing.T) {
	var stderr bytes.Buffer
	code := execute(context.Background(), environment(map[string]string{
		"DATABASE_URL": testdb.URL(), "GREENHOUSE_BOARDS": "ottermere,quillfeather",
	}), &stderr, feed(t))
	if code != 0 {
		t.Errorf("exit code %d, want 0; standard error:\n%s", code, &stderr)
	}
}

func TestExitsOneWhenAnyBoardFails(t *testing.T) {
	var stderr bytes.Buffer
	code := execute(context.Background(), environment(map[string]string{
		"DATABASE_URL": testdb.URL(), "GREENHOUSE_BOARDS": "larkspur,ottermere",
	}), &stderr, feed(t))
	if code != 1 {
		t.Errorf("exit code %d, want 1; standard error:\n%s", code, &stderr)
	}
}

func TestExitsTwoWhenTheSettingsAreRefused(t *testing.T) {
	var stderr bytes.Buffer
	code := execute(context.Background(), environment(map[string]string{
		"DATABASE_URL": testdb.URL(), "GREENHOUSE_BOARDS": "Not A Token",
	}), &stderr, feed(t))
	if code != 2 {
		t.Errorf("exit code %d, want 2", code)
	}
	if !strings.Contains(stderr.String(), "GREENHOUSE_BOARDS") {
		t.Errorf("standard error %q does not name the setting", &stderr)
	}
}

func TestExitsTwoWhenTheDatabaseCannotBeReached(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	_ = listener.Close() // nothing listens on the port from here on

	var stderr bytes.Buffer
	code := execute(context.Background(), environment(map[string]string{
		"DATABASE_URL":      fmt.Sprintf("postgresql://job_board:s3cret@127.0.0.1:%d/job_board", port),
		"GREENHOUSE_BOARDS": "ottermere",
	}), &stderr, feed(t))
	if code != 2 {
		t.Errorf("exit code %d, want 2", code)
	}
	if message := stderr.String(); !strings.Contains(message, "DATABASE_URL") || strings.Contains(message, "s3cret") {
		t.Errorf("standard error %q should name the setting and never its password", message)
	}
}

func TestExitsTwoWhenTheDatabaseIsNotMigrated(t *testing.T) {
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	// A schema with no tables in it stands in for a database nobody migrated.
	if _, err := conn.Exec(ctx, "CREATE SCHEMA IF NOT EXISTS unmigrated"); err != nil {
		t.Fatal(err)
	}

	var stderr bytes.Buffer
	code := execute(ctx, environment(map[string]string{
		"DATABASE_URL":      withParameter(t, testdb.URL(), "search_path", "unmigrated"),
		"GREENHOUSE_BOARDS": "ottermere",
	}), &stderr, feed(t))

	if code != 2 {
		t.Errorf("exit code %d, want 2; standard error:\n%s", code, &stderr)
	}
	if message := stderr.String(); !strings.Contains(message, "not migrated") ||
		!strings.Contains(message, "uv run alembic upgrade head") {
		t.Errorf("standard error %q should say the database is not migrated and how to migrate it", message)
	}
}

func TestExitsTwoNamingTheCauseWhenTheServerRefusesTheConnection(t *testing.T) {
	cases := []struct {
		name, databaseURL, cause string
	}{
		{name: "a missing database", cause: "does not exist (PostgreSQL condition 3D000)",
			databaseURL: withDatabase(t, testdb.URL(), "job_board_no_such_database")},
		{name: "a refused password", cause: "refused the user name or password in DATABASE_URL (PostgreSQL condition 28P01)",
			databaseURL: withPassword(t, testdb.URL(), "not-the-password")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var stderr bytes.Buffer
			code := execute(context.Background(), environment(map[string]string{
				"DATABASE_URL": c.databaseURL, "GREENHOUSE_BOARDS": "ottermere",
			}), &stderr, feed(t))

			if code != 2 {
				t.Errorf("exit code %d, want 2", code)
			}
			message := stderr.String()
			if !strings.Contains(message, c.cause) {
				t.Errorf("standard error %q does not name the cause %q", message, c.cause)
			}
			if strings.Contains(message, "docker compose") || strings.Contains(message, "not-the-password") {
				t.Errorf("standard error %q sends a reachable server's refusal to docker, or leaks the password", message)
			}
		})
	}
}

func withParameter(t *testing.T, databaseURL, key, value string) string {
	t.Helper()
	parsed := parse(t, databaseURL)
	query := parsed.Query()
	query.Set(key, value)
	parsed.RawQuery = query.Encode()
	return parsed.String()
}

func withDatabase(t *testing.T, databaseURL, name string) string {
	t.Helper()
	parsed := parse(t, databaseURL)
	parsed.Path = "/" + name
	return parsed.String()
}

func withPassword(t *testing.T, databaseURL, password string) string {
	t.Helper()
	parsed := parse(t, databaseURL)
	parsed.User = url.UserPassword(parsed.User.Username(), password)
	return parsed.String()
}

func parse(t *testing.T, databaseURL string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

package main

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
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
	if _, err := conn.Exec(ctx, "TRUNCATE postings, fetch_runs"); err != nil {
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

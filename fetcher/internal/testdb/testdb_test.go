package testdb

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func testServer(t *testing.T) string {
	t.Helper()
	server, err := serverURL(os.Getenv("DATABASE_URL"), filepath.Join(repositoryRoot(), "backend", ".env.example"))
	if err != nil {
		t.Fatal(err)
	}
	return server
}

func adminConnection(t *testing.T, server string) *pgx.Conn {
	t.Helper()
	conn, err := connect(context.Background(), server)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close(context.Background()) })
	return conn
}

func existing(t *testing.T, conn *pgx.Conn, names []string) []string {
	t.Helper()
	rows, err := conn.Query(context.Background(), "SELECT datname FROM pg_database WHERE datname = ANY($1) ORDER BY 1", names)
	if err != nil {
		t.Fatal(err)
	}
	found, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	return found
}

func TestCreatesADatabaseNamedAsTheBackendNamesItsOwn(t *testing.T) {
	ctx := context.Background()
	server := testServer(t)
	now := time.Now()
	name, err := create(ctx, server, now)
	if err != nil {
		t.Fatal(err)
	}
	conn := adminConnection(t, server)
	t.Cleanup(func() { _ = drop(ctx, server, name) })

	if created, ok := createdAt(name); !ok || created.Format(timestampLayout) != now.UTC().Format(timestampLayout) {
		t.Errorf("name %q does not carry its UTC creation time", name)
	}
	if !strings.HasPrefix(name, "job_board_test_") || len(name) != len("job_board_test_")+14+1+12 {
		t.Errorf("name %q is not job_board_test_<14 digits>_<12 hex>", name)
	}
	if got := existing(t, conn, []string{name}); len(got) != 1 {
		t.Fatalf("database %s was not created", name)
	}
	if err := drop(ctx, server, name); err != nil {
		t.Fatal(err)
	}
	if got := existing(t, conn, []string{name}); len(got) != 0 {
		t.Errorf("database %s was not dropped", name)
	}
}

func TestDropsTestDatabasesOlderThanADayAndNothingElse(t *testing.T) {
	ctx := context.Background()
	conn := adminConnection(t, testServer(t))
	now := time.Now().UTC()
	stale := "job_board_test_" + now.Add(-staleAfter-time.Hour).Format(timestampLayout) + "_0123456789ab"
	recent := "job_board_test_" + now.Add(-time.Hour).Format(timestampLayout) + "_0123456789ab"
	unparsable := "job_board_test_0123456789ab"
	planted := []string{stale, recent, unparsable}
	for _, name := range planted {
		if _, err := conn.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()); err != nil {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() {
		for _, name := range planted {
			_, _ = conn.Exec(ctx, "DROP DATABASE IF EXISTS "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)")
		}
	})

	if _, err := dropStale(ctx, conn, now); err != nil {
		t.Fatal(err)
	}
	want := []string{recent, unparsable}
	slices.Sort(want)
	if got := existing(t, conn, planted); !slices.Equal(got, want) {
		t.Errorf("left %v, want %v", got, want)
	}
}

func TestServerURLPrefersTheVariableThenTheExampleFile(t *testing.T) {
	example := filepath.Join(t.TempDir(), ".env.example")
	contents := "# a comment\nDATABASE_URL=postgres://someone:pw@db.example.com:6543/other\n"
	if err := os.WriteFile(example, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
	if got, _ := serverURL("", example); got != "postgres://someone:pw@db.example.com:6543/other" {
		t.Errorf("from the example file: %q", got)
	}
	if got, _ := serverURL("postgresql://a:b@db.example.com/x", example); got != "postgresql://a:b@db.example.com/x" {
		t.Errorf("from the variable: %q", got)
	}
}

func TestAnUnreachableServerIsNamedByTheCommandThatStartsIt(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	_ = listener.Close() // nothing listens on the port from here on

	_, err = create(context.Background(), fmt.Sprintf("postgresql://job_board:s3cret@127.0.0.1:%d/job_board", port), time.Now())
	if !errors.Is(err, errUnreachable) {
		t.Fatalf("create error = %v, want the unreachable message", err)
	}
	for _, leak := range []string{"s3cret", fmt.Sprint(port), "127.0.0.1"} {
		if strings.Contains(err.Error(), leak) {
			t.Errorf("the message names %q", leak)
		}
	}
	if !strings.Contains(err.Error(), startCommand) {
		t.Errorf("the message %q does not give the start command", err)
	}
}

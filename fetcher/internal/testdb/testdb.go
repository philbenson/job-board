// Package testdb gives a package's tests a PostgreSQL database of their own,
// migrated to the newest schema, and drops it when they finish.
//
// Invariant: parallel test runs never share a database. Each test binary
// creates a uniquely named database on the shared server and drops it at the
// end, so several checkouts, and the backend's tests, can use one server at
// once. The names have the backend's shape, job_board_test_<UTC time>_<hex>,
// so whichever suite starts next clears the databases a killed run of either
// left behind.
package testdb

import (
	"cmp"
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	namePrefix      = "job_board_test_"
	timestampLayout = "20060102150405" // UTC; the backend writes it as %Y%m%d%H%M%S
	// Far longer than any test run, so a live parallel run's database is never dropped.
	staleAfter     = 24 * time.Hour
	connectTimeout = 5 * time.Second // a server that is down fails the run promptly instead of hanging it
	startCommand   = "docker compose up -d --wait db"
)

const urlForm = "DATABASE_URL for the tests must have the form postgresql://user:password@host:port/database"

var testName = regexp.MustCompile(`^job_board_test_(\d{14})_[0-9a-f]+$`)

var errUnreachable = errors.New("could not connect to PostgreSQL for the tests. " +
	"If it is the local database, start it from the repository root with: " + startCommand)

var databaseURL string

// URL is the address of this test binary's database; Main sets it.
func URL() string {
	if databaseURL == "" {
		panic("testdb.URL called outside a TestMain that runs testdb.Main")
	}
	return databaseURL
}

// Main creates and migrates the database, runs the tests, drops the database
// and exits. Call it from TestMain. A server it cannot reach fails the run with
// the command that starts the local one; it never skips the tests.
func Main(m *testing.M) {
	os.Exit(run(m))
}

func run(m *testing.M) int {
	ctx := context.Background()
	server, err := serverURL(os.Getenv("DATABASE_URL"), filepath.Join(repositoryRoot(), "backend", ".env.example"))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	name, err := create(ctx, server, time.Now())
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	defer func() {
		if err := drop(ctx, server, name); err != nil {
			fmt.Fprintf(os.Stderr, "could not drop the test database %s: %v\n", name, err)
		}
	}()

	databaseURL, err = withDatabase(server, name)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if err := migrate(databaseURL); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return m.Run()
}

// repositoryRoot is found from this file's own path, so it is the same from
// whichever package's folder the tests run.
func repositoryRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..", "..")
}

// serverURL is DATABASE_URL, else the DATABASE_URL= line of the example file;
// never backend/.env, which is the service's own and may name a database the
// tests must not touch.
func serverURL(fromEnvironment, exampleFile string) (string, error) {
	if fromEnvironment != "" {
		return fromEnvironment, nil
	}
	contents, err := os.ReadFile(exampleFile)
	if err != nil {
		return "", fmt.Errorf("DATABASE_URL is not set and the example file cannot be read: %w", err)
	}
	for line := range strings.Lines(string(contents)) {
		key, value, found := strings.Cut(line, "=")
		if found && strings.TrimSpace(key) == "DATABASE_URL" {
			return strings.TrimSpace(value), nil
		}
	}
	return "", fmt.Errorf("DATABASE_URL is not set and %s has no DATABASE_URL= line", filepath.Base(exampleFile))
}

func connect(ctx context.Context, server string) (*pgx.Conn, error) {
	config, err := pgx.ParseConfig(server)
	if err != nil {
		return nil, errors.New(urlForm)
	}
	config.ConnectTimeout = cmp.Or(config.ConnectTimeout, connectTimeout)
	conn, err := pgx.ConnectConfig(ctx, config)
	if err != nil {
		return nil, errUnreachable // the driver's message would name the server, never needed here
	}
	return conn, nil
}

// create drops stale test databases, then creates a new one and names it.
func create(ctx context.Context, server string, now time.Time) (string, error) {
	conn, err := connect(ctx, server)
	if err != nil {
		return "", err
	}
	defer conn.Close(ctx)

	if _, err := dropStale(ctx, conn, now); err != nil {
		return "", err
	}
	suffix := make([]byte, 6)
	_, _ = rand.Read(suffix) // never fails, by crypto/rand's contract
	name := namePrefix + now.UTC().Format(timestampLayout) + "_" + hex.EncodeToString(suffix)
	if _, err := conn.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize()); err != nil {
		return "", fmt.Errorf("could not create the test database: %w", err)
	}
	return name, nil
}

// createdAt is when a test database was made, from its name; false for any
// name not of the test databases' shape.
func createdAt(name string) (time.Time, bool) {
	match := testName.FindStringSubmatch(name)
	if match == nil {
		return time.Time{}, false
	}
	created, err := time.Parse(timestampLayout, match[1])
	return created, err == nil
}

// dropStale drops test databases more than staleAfter old, left by runs that
// never finished, and names them.
func dropStale(ctx context.Context, conn *pgx.Conn, now time.Time) ([]string, error) {
	rows, err := conn.Query(ctx, "SELECT datname FROM pg_database WHERE starts_with(datname, $1)", namePrefix)
	if err != nil {
		return nil, err
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	var dropped []string
	for _, name := range names {
		if created, ok := createdAt(name); ok && now.Sub(created) > staleAfter {
			if _, err := conn.Exec(ctx, "DROP DATABASE IF EXISTS "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)"); err != nil {
				return dropped, err
			}
			dropped = append(dropped, name)
		}
	}
	return dropped, nil
}

func drop(ctx context.Context, server, name string) error {
	conn, err := connect(ctx, server)
	if err != nil {
		return err
	}
	defer conn.Close(ctx)
	_, err = conn.Exec(ctx, "DROP DATABASE IF EXISTS "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)")
	return err
}

// withDatabase is server's URL naming database name instead.
func withDatabase(server, name string) (string, error) {
	parsed, err := url.Parse(server)
	if err != nil || (parsed.Scheme != "postgresql" && parsed.Scheme != "postgres") {
		return "", errors.New(urlForm)
	}
	parsed.Path = "/" + name
	return parsed.String(), nil
}

// migrate brings the database to the newest schema with the backend's own
// migrations, since the fetcher never creates a table itself.
func migrate(database string) error {
	command := exec.Command("uv", "run", "--locked", "alembic", "upgrade", "head")
	command.Dir = filepath.Join(repositoryRoot(), "backend")
	command.Env = append(os.Environ(), "DATABASE_URL="+database)
	if output, err := command.CombinedOutput(); err != nil {
		return fmt.Errorf("could not migrate the test database (uv run alembic upgrade head in backend/): %v\n%s", err, output)
	}
	return nil
}

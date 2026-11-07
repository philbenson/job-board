package run

import (
	"bytes"
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/philbenson/job-board/fetcher/internal/greenhouse"
	"github.com/philbenson/job-board/fetcher/internal/store"
	"github.com/philbenson/job-board/fetcher/internal/testdb"
)

func TestMain(m *testing.M) {
	testdb.Main(m)
}

var fixture = func() []byte {
	body, err := os.ReadFile("../greenhouse/testdata/board.json")
	if err != nil {
		panic(err)
	}
	return body
}()

// feeds answers each board's request with its own handler; a board with none is a 404.
type feeds map[string]http.HandlerFunc

func (f feeds) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	board := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/boards/"), "/jobs")
	if handler, ok := f[board]; ok {
		handler(w, r)
		return
	}
	http.NotFound(w, r)
}

func answer(body []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write(body) }
}

// harness is a Runner wired to a stand-in feed and the test database, with its
// log captured. Both tables are emptied when the test ends.
type harness struct {
	runner *Runner
	feeds  feeds
	log    *bytes.Buffer
	conn   *pgx.Conn
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	ctx := context.Background()
	s, err := store.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	h := &harness{feeds: feeds{}, log: &bytes.Buffer{}, conn: conn}
	server := httptest.NewServer(h.feeds)
	h.runner = &Runner{
		Feed:  &greenhouse.Client{BaseURL: server.URL},
		Store: s,
		Log:   slog.New(slog.NewTextHandler(h.log, nil)),
	}
	t.Cleanup(func() {
		server.Close()
		if _, err := conn.Exec(ctx, "TRUNCATE postings, fetch_runs"); err != nil {
			t.Error(err)
		}
		_ = s.Close(ctx)
		_ = conn.Close(ctx)
	})
	return h
}

// useStore replaces the runner's store with one connected to databaseURL.
func (h *harness) useStore(t *testing.T, databaseURL string) {
	t.Helper()
	ctx := context.Background()
	s, err := store.Connect(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close(ctx) })
	h.runner.Store = s
}

// withParameter adds a query parameter to a database URL; pgx passes one it
// does not know to the server as a setting for the session.
func withParameter(t *testing.T, databaseURL, key, value string) string {
	t.Helper()
	parsed, err := url.Parse(databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	query := parsed.Query()
	query.Set(key, value)
	parsed.RawQuery = query.Encode()
	return parsed.String()
}

// postings is a board's rows, every column but the id, in a comparable form.
func (h *harness) postings(t *testing.T, board string) []string {
	t.Helper()
	return h.strings(t, `
		SELECT format('%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s', external_id, title, company_name, location, url,
		              md5(content_html), first_published_at, source_updated_at, first_seen_at, last_seen_at, closed_at)
		FROM postings WHERE board = $1 ORDER BY external_id`, board)
}

// runs is every fetch_runs row as "board outcome failure seen/new/closed", oldest first.
func (h *harness) runs(t *testing.T) []string {
	t.Helper()
	return h.strings(t, `
		SELECT format('%s %s %s %s/%s/%s', board, outcome, coalesce(failure, '-'),
		              postings_seen, postings_new, postings_closed)
		FROM fetch_runs ORDER BY id`)
}

func (h *harness) strings(t *testing.T, query string, arguments ...any) []string {
	t.Helper()
	rows, err := h.conn.Query(context.Background(), query, arguments...)
	if err != nil {
		t.Fatal(err)
	}
	read, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	return read
}

func TestARunOverTheFixtureStoresItsPostingsAndASucceededRun(t *testing.T) {
	h := newHarness(t)
	h.feeds["ottermere"] = answer(fixture)

	if ok := h.runner.Boards(context.Background(), []string{"ottermere"}); !ok {
		t.Errorf("Boards reported a failure; log:\n%s", h.log)
	}

	if got := len(h.postings(t, "ottermere")); got != 3 {
		t.Errorf("stored %d postings, want 3", got)
	}
	if got, want := h.runs(t), []string{"ottermere succeeded - 3/3/0"}; !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q", got, want)
	}
	if line := h.log.String(); !strings.Contains(line, "board=ottermere outcome=succeeded seen=3 new=3 closed=0") {
		t.Errorf("log %q does not report the board", line)
	}
}

func TestAFailedBoardKeepsItsPostingsAndRecordsWhy(t *testing.T) {
	cases := []struct {
		name    string
		answer  http.HandlerFunc
		adjust  func(*testing.T, *harness)
		failure string
		detail  string // what the log line says beside the failure code; never a URL or a server's text
	}{
		{name: "a server error", failure: "status", detail: "http_status=500",
			answer: func(w http.ResponseWriter, r *http.Request) { http.Error(w, "oops", http.StatusInternalServerError) }},
		{name: "malformed JSON", failure: "decode", answer: answer([]byte(`{"jobs": [`))},
		{name: "an invalid posting", failure: "invalid-posting", detail: "posting=1 check=title",
			answer: answer([]byte(`{"jobs": [{"id": 1, "title": " ", "absolute_url": "https://jobs.example.com/1", "updated_at": "2026-11-01T00:00:00Z"}]}`))},
		{name: "a body over the cap", failure: "too-large", answer: answer(fixture),
			adjust: func(t *testing.T, h *harness) { h.runner.Feed.MaxBodyBytes = int64(len(fixture)) - 1 }},
		{name: "a server that never answers", failure: "request", detail: "timed_out=true",
			answer: func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() },
			adjust: func(t *testing.T, h *harness) { h.runner.Feed.Timeout = 50 * time.Millisecond }},
		{name: "a server that hangs up", failure: "request", detail: "timed_out=false",
			answer: func(w http.ResponseWriter, r *http.Request) { panic(http.ErrAbortHandler) }},
		// PostgreSQL refuses a NUL byte in text, so this feed decodes but cannot be stored.
		{name: "a posting the database refuses", failure: "database", detail: "condition=22021",
			answer: answer([]byte(`{"jobs": [{"id": 1, "title": "Engineer\u0000", "absolute_url": "https://jobs.example.com/1", "updated_at": "2026-11-01T00:00:00Z"}]}`))},
		{name: "a row the write cannot lock in time", failure: "database", detail: "condition=55P03",
			answer: answer(fixture),
			adjust: func(t *testing.T, h *harness) {
				h.useStore(t, withParameter(t, testdb.URL(), "lock_timeout", "100"))
				holdRow(t, 1001)
			}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			h.feeds["ottermere"] = answer(fixture)
			h.runner.Boards(context.Background(), []string{"ottermere"})
			before := h.postings(t, "ottermere")

			h.feeds["ottermere"] = c.answer
			if c.adjust != nil {
				c.adjust(t, h)
			}
			if ok := h.runner.Boards(context.Background(), []string{"ottermere"}); ok {
				t.Error("Boards reported success")
			}

			if after := h.postings(t, "ottermere"); !reflect.DeepEqual(after, before) {
				t.Errorf("the failed run changed the postings:\n got %q\nwant %q", after, before)
			}
			want := []string{"ottermere succeeded - 3/3/0", "ottermere failed " + c.failure + " 0/0/0"}
			if got := h.runs(t); !reflect.DeepEqual(got, want) {
				t.Errorf("runs %q, want %q", got, want)
			}
			report := strings.TrimSpace("board=ottermere outcome=failed failure=" + c.failure + " " + c.detail)
			if line := h.log.String(); !strings.Contains(line, report+"\n") {
				t.Errorf("log %q does not say %q", line, report)
			}
		})
	}
}

func TestOneBoardFailingNeverStopsAnother(t *testing.T) {
	h := newHarness(t)
	h.feeds["larkspur"] = func(w http.ResponseWriter, r *http.Request) { http.Error(w, "oops", http.StatusBadGateway) }
	h.feeds["ottermere"] = answer(fixture)

	if ok := h.runner.Boards(context.Background(), []string{"larkspur", "ottermere"}); ok {
		t.Error("Boards reported success")
	}

	if got := len(h.postings(t, "ottermere")); got != 3 {
		t.Errorf("stored %d postings for the working board, want 3", got)
	}
	want := []string{"larkspur failed status 0/0/0", "ottermere succeeded - 3/3/0"}
	if got := h.runs(t); !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q", got, want)
	}
}

func TestAnInterruptedRunRecordsTheBoardItWasOnAndStartsNoOther(t *testing.T) {
	h := newHarness(t)
	ctx, interrupt := context.WithCancel(context.Background())
	defer interrupt()
	h.feeds["larkspur"] = func(w http.ResponseWriter, r *http.Request) {
		interrupt() // as SIGINT would, while the board is being fetched
		<-r.Context().Done()
	}
	h.feeds["ottermere"] = answer(fixture)

	if ok := h.runner.Boards(ctx, []string{"larkspur", "ottermere"}); ok {
		t.Error("Boards reported success")
	}

	if got, want := h.runs(t), []string{"larkspur failed interrupted 0/0/0"}; !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q", got, want)
	}
	if got := len(h.postings(t, "ottermere")); got != 0 {
		t.Errorf("stored %d postings for a board after the interrupt", got)
	}
	if line := h.log.String(); !strings.Contains(line, "board=ottermere outcome=skipped reason=interrupted") {
		t.Errorf("log %q does not report the skipped board", line)
	}
}

func TestADroppedConnectionFailsOnlyTheBoardInHand(t *testing.T) {
	h := newHarness(t)
	h.feeds["larkspur"] = func(w http.ResponseWriter, r *http.Request) {
		// As a database restart would, end every other session while the board is being fetched.
		_, err := h.conn.Exec(r.Context(), `
			SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity
			WHERE datname = current_database() AND pid <> pg_backend_pid()`)
		if err != nil {
			t.Error(err)
		}
		_, _ = w.Write(fixture)
	}
	h.feeds["ottermere"] = answer(fixture)

	if ok := h.runner.Boards(context.Background(), []string{"larkspur", "ottermere"}); ok {
		t.Error("Boards reported success")
	}

	want := []string{"larkspur failed database 0/0/0", "ottermere succeeded - 3/3/0"}
	if got := h.runs(t); !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q; log:\n%s", got, want, h.log)
	}
	if got := len(h.postings(t, "larkspur")); got != 0 {
		t.Errorf("stored %d postings for the board whose connection dropped, want 0", got)
	}
	if got := len(h.postings(t, "ottermere")); got != 3 {
		t.Errorf("stored %d postings for the next board, want 3", got)
	}
}

func TestAnInterruptDuringTheWriteRollsItBackAndRecordsIt(t *testing.T) {
	h := newHarness(t)
	h.feeds["ottermere"] = answer(fixture)
	h.runner.Boards(context.Background(), []string{"ottermere"})
	before := h.postings(t, "ottermere")
	holdRow(t, 1001) // so the next write waits inside its transaction

	ctx, interrupt := context.WithCancel(context.Background())
	defer interrupt()
	waited := make(chan struct{})
	go func() {
		defer close(waited)
		interruptOnceWaiting(t, interrupt)
	}()
	ok := h.runner.Boards(ctx, []string{"ottermere"})
	<-waited

	if ok {
		t.Error("Boards reported success")
	}
	want := []string{"ottermere succeeded - 3/3/0", "ottermere failed interrupted 0/0/0"}
	if got := h.runs(t); !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q; log:\n%s", got, want, h.log)
	}
	if after := h.postings(t, "ottermere"); !reflect.DeepEqual(after, before) {
		t.Errorf("the interrupted write changed the postings:\n got %q\nwant %q", after, before)
	}
}

// holdRow locks one posting's row from a connection of its own until the test
// ends, so any write that touches it waits.
func holdRow(t *testing.T, externalID int64) {
	t.Helper()
	ctx := context.Background()
	holder, err := pgx.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	tx, err := holder.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, "SELECT 1 FROM postings WHERE external_id = $1 FOR UPDATE", externalID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = tx.Rollback(ctx)
		_ = holder.Close(ctx)
	})
}

// interruptOnceWaiting calls interrupt as soon as a session of the test
// database is waiting for a lock, as SIGINT would during a write.
func interruptOnceWaiting(t *testing.T, interrupt context.CancelFunc) {
	ctx := context.Background()
	watcher, err := pgx.Connect(ctx, testdb.URL())
	if err != nil {
		t.Error(err)
		interrupt()
		return
	}
	defer watcher.Close(ctx)
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		var waiting int
		err := watcher.QueryRow(ctx, `
			SELECT count(*) FROM pg_stat_activity
			WHERE datname = current_database() AND wait_event_type = 'Lock'`).Scan(&waiting)
		if err != nil {
			t.Error(err)
			break
		}
		if waiting > 0 {
			interrupt()
			return
		}
	}
	t.Error("no write waited for the held row")
	interrupt()
}

func TestABoardAnotherRunIsFetchingIsRecordedAsLockedAndNotFetched(t *testing.T) {
	h := newHarness(t)
	ctx := context.Background()
	other, err := store.Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close(ctx)
	if _, err := other.LockBoard(ctx, greenhouse.Source, "larkspur"); err != nil {
		t.Fatal(err)
	}
	requests := 0
	h.feeds["larkspur"] = func(w http.ResponseWriter, r *http.Request) {
		requests++
		_, _ = w.Write(fixture)
	}
	h.feeds["ottermere"] = answer(fixture)

	if ok := h.runner.Boards(ctx, []string{"larkspur", "ottermere"}); ok {
		t.Error("Boards reported success")
	}

	if requests != 0 {
		t.Errorf("the locked board was fetched %d times, want 0", requests)
	}
	want := []string{"larkspur failed locked 0/0/0", "ottermere succeeded - 3/3/0"}
	if got := h.runs(t); !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q; log:\n%s", got, want, h.log)
	}
	if line := h.log.String(); !strings.Contains(line, `level=WARN msg="board fetched" board=larkspur outcome=failed failure=locked`) {
		t.Errorf("log %q does not warn of the locked board", line)
	}
}

package run

import (
	"bytes"
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
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
		adjust  func(*greenhouse.Client)
		failure string
	}{
		{name: "a server error", failure: "status",
			answer: func(w http.ResponseWriter, r *http.Request) { http.Error(w, "oops", http.StatusInternalServerError) }},
		{name: "malformed JSON", failure: "decode", answer: answer([]byte(`{"jobs": [`))},
		{name: "an invalid posting", failure: "invalid-posting",
			answer: answer([]byte(`{"jobs": [{"id": 1, "title": " ", "absolute_url": "https://jobs.example.com/1", "updated_at": "2026-11-01T00:00:00Z"}]}`))},
		{name: "a body over the cap", failure: "too-large", answer: answer(fixture),
			adjust: func(c *greenhouse.Client) { c.MaxBodyBytes = int64(len(fixture)) - 1 }},
		{name: "a server that never answers", failure: "request",
			answer: func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() },
			adjust: func(c *greenhouse.Client) { c.Timeout = 50 * time.Millisecond }},
		// PostgreSQL refuses a NUL byte in text, so this feed decodes but cannot be stored.
		{name: "a posting the database refuses", failure: "database",
			answer: answer([]byte(`{"jobs": [{"id": 1, "title": "Engineer\u0000", "absolute_url": "https://jobs.example.com/1", "updated_at": "2026-11-01T00:00:00Z"}]}`))},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			h.feeds["ottermere"] = answer(fixture)
			h.runner.Boards(context.Background(), []string{"ottermere"})
			before := h.postings(t, "ottermere")

			h.feeds["ottermere"] = c.answer
			if c.adjust != nil {
				c.adjust(h.runner.Feed)
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
			if line := h.log.String(); !strings.Contains(line, "board=ottermere outcome=failed failure="+c.failure) {
				t.Errorf("log %q does not report the failure", line)
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

	if got, want := h.runs(t), []string{"larkspur failed request 0/0/0"}; !reflect.DeepEqual(got, want) {
		t.Errorf("runs %q, want %q", got, want)
	}
	if got := len(h.postings(t, "ottermere")); got != 0 {
		t.Errorf("stored %d postings for a board after the interrupt", got)
	}
	if line := h.log.String(); !strings.Contains(line, "board=ottermere outcome=skipped reason=interrupted") {
		t.Errorf("log %q does not report the skipped board", line)
	}
}

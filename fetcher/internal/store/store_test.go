package store

import (
	"context"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/philbenson/job-board/fetcher/internal/posting"
	"github.com/philbenson/job-board/fetcher/internal/testdb"
)

func TestMain(m *testing.M) {
	testdb.Main(m)
}

// row is a postings row as the tests read it back.
type row struct {
	ExternalID       int64      `db:"external_id"`
	Title            string     `db:"title"`
	CompanyName      *string    `db:"company_name"`
	Location         *string    `db:"location"`
	URL              string     `db:"url"`
	ContentHTML      *string    `db:"content_html"`
	FirstPublishedAt *time.Time `db:"first_published_at"`
	SourceUpdatedAt  time.Time  `db:"source_updated_at"`
	FirstSeenAt      time.Time  `db:"first_seen_at"`
	LastSeenAt       time.Time  `db:"last_seen_at"`
	ClosedAt         *time.Time `db:"closed_at"`
}

// open connects to the test database and empties both tables when the test ends.
func open(t *testing.T) *Store {
	t.Helper()
	ctx := context.Background()
	s, err := Connect(ctx, testdb.URL())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := s.conn.Exec(ctx, "TRUNCATE postings, fetch_runs"); err != nil {
			t.Error(err)
		}
		_ = s.Close(ctx)
	})
	return s
}

// rows reads a board's postings in id order, and fails the test unless there are want of them.
func rows(t *testing.T, s *Store, board string, want int) []row {
	t.Helper()
	result, err := s.conn.Query(context.Background(), `
		SELECT external_id, title, company_name, location, url, content_html, first_published_at,
		       source_updated_at, first_seen_at, last_seen_at, closed_at
		FROM postings WHERE source = 'greenhouse' AND board = $1 ORDER BY external_id`, board)
	if err != nil {
		t.Fatal(err)
	}
	read, err := pgx.CollectRows(result, pgx.RowToStructByName[row])
	if err != nil {
		t.Fatal(err)
	}
	if len(read) != want {
		t.Fatalf("board %s has %d postings, want %d", board, len(read), want)
	}
	return read
}

func sample(id int64, title string) posting.Posting {
	published := time.Date(2026, 10, 1, 13, 0, 0, 0, time.UTC)
	return posting.Posting{
		ExternalID:       id,
		Title:            title,
		CompanyName:      "Ottermere Analytics",
		Location:         "Remote",
		URL:              "https://jobs.example.com/ottermere/1",
		ContentHTML:      "<p>Count the otters.</p>",
		FirstPublishedAt: &published,
		SourceUpdatedAt:  time.Date(2026, 10, 2, 13, 0, 0, 0, time.UTC),
	}
}

func write(t *testing.T, s *Store, board string, postings ...posting.Posting) Counts {
	t.Helper()
	counts, err := s.WriteBoard(context.Background(), "greenhouse", board, postings)
	if err != nil {
		t.Fatalf("WriteBoard: %v", err)
	}
	return counts
}

func TestWriteBoardStoresNewPostings(t *testing.T) {
	s := open(t)
	bare := posting.Posting{
		ExternalID:      2,
		Title:           "Product Designer",
		URL:             "https://jobs.example.com/ottermere/2",
		SourceUpdatedAt: time.Date(2026, 10, 3, 13, 0, 0, 0, time.UTC),
	}

	counts := write(t, s, "ottermere", sample(1, "Data Engineer"), bare, sample(3, "Site Reliability Engineer"))

	if want := (Counts{Seen: 3, New: 3}); counts != want {
		t.Errorf("counts %+v, want %+v", counts, want)
	}
	stored := rows(t, s, "ottermere", 3)
	full := stored[0]
	if full.Title != "Data Engineer" || *full.CompanyName != "Ottermere Analytics" || *full.Location != "Remote" ||
		*full.ContentHTML != "<p>Count the otters.</p>" || !full.FirstPublishedAt.Equal(*sample(1, "").FirstPublishedAt) ||
		!full.SourceUpdatedAt.Equal(sample(1, "").SourceUpdatedAt) || full.ClosedAt != nil ||
		!full.FirstSeenAt.Equal(full.LastSeenAt) {
		t.Errorf("stored %+v", full)
	}
	empty := stored[1]
	if empty.CompanyName != nil || empty.Location != nil || empty.ContentHTML != nil || empty.FirstPublishedAt != nil {
		t.Errorf("absent fields should be NULL, got %+v", empty)
	}
}

func TestWriteBoardTwiceChangesNothingButLastSeen(t *testing.T) {
	s := open(t)
	postings := []posting.Posting{sample(1, "Data Engineer"), sample(2, "Product Designer")}
	write(t, s, "ottermere", postings...)
	before := rows(t, s, "ottermere", 2)

	counts := write(t, s, "ottermere", postings...)

	if want := (Counts{Seen: 2}); counts != want {
		t.Errorf("counts %+v, want %+v", counts, want)
	}
	after := rows(t, s, "ottermere", 2)
	for i := range after {
		if !after[i].LastSeenAt.After(before[i].LastSeenAt) {
			t.Errorf("posting %d: last_seen_at did not advance", after[i].ExternalID)
		}
		after[i].LastSeenAt = before[i].LastSeenAt
		if !reflect.DeepEqual(after[i], before[i]) {
			t.Errorf("posting %d changed:\n got %+v\nwant %+v", after[i].ExternalID, after[i], before[i])
		}
	}
}

func TestWriteBoardClosesAPostingThatIsGoneAndReopensItWhenItReturns(t *testing.T) {
	s := open(t)
	write(t, s, "ottermere", sample(1, "Data Engineer"), sample(2, "Product Designer"))

	counts := write(t, s, "ottermere", sample(1, "Data Engineer"))

	if want := (Counts{Seen: 1, Closed: 1}); counts != want {
		t.Errorf("closing: counts %+v, want %+v", counts, want)
	}
	gone := rows(t, s, "ottermere", 2)[1]
	if gone.ClosedAt == nil {
		t.Fatal("posting 2 is still open")
	}
	if seen := rows(t, s, "ottermere", 2)[0]; !gone.ClosedAt.Equal(seen.LastSeenAt) {
		t.Errorf("closed at %v, want the write's time %v", gone.ClosedAt, seen.LastSeenAt)
	}

	counts = write(t, s, "ottermere", sample(1, "Data Engineer"), sample(2, "Product Designer"))

	if want := (Counts{Seen: 2}); counts != want {
		t.Errorf("reopening: counts %+v, want %+v", counts, want)
	}
	back := rows(t, s, "ottermere", 2)[1]
	if back.ClosedAt != nil {
		t.Errorf("posting 2 is still closed at %v", back.ClosedAt)
	}
	if !back.FirstSeenAt.Equal(gone.FirstSeenAt) {
		t.Errorf("reopening moved first_seen_at from %v to %v", gone.FirstSeenAt, back.FirstSeenAt)
	}
}

func TestWriteBoardUpdatesEveryFieldOfAChangedPosting(t *testing.T) {
	s := open(t)
	write(t, s, "ottermere", sample(1, "Data Engineer"))
	first := rows(t, s, "ottermere", 1)[0]
	republished := time.Date(2026, 10, 20, 9, 30, 0, 0, time.UTC)
	changed := posting.Posting{
		ExternalID:       1,
		Title:            "Senior Data Engineer",
		CompanyName:      "Ottermere Analytics Group",
		Location:         "", // was "Remote": an optional field emptied must become NULL
		URL:              "https://jobs.example.com/ottermere/1-senior",
		ContentHTML:      "<p>Count more otters.</p>",
		FirstPublishedAt: &republished,
		SourceUpdatedAt:  time.Date(2026, 10, 21, 9, 30, 0, 0, time.UTC),
	}

	write(t, s, "ottermere", changed)

	got := rows(t, s, "ottermere", 1)[0]
	company, content := changed.CompanyName, changed.ContentHTML
	want := row{
		ExternalID:       1,
		Title:            changed.Title,
		CompanyName:      &company,
		Location:         nil,
		URL:              changed.URL,
		ContentHTML:      &content,
		FirstPublishedAt: got.FirstPublishedAt,
		SourceUpdatedAt:  got.SourceUpdatedAt,
		FirstSeenAt:      first.FirstSeenAt,
		LastSeenAt:       got.LastSeenAt,
		ClosedAt:         nil,
	}
	// Times read back in the session's zone, so compare them as instants.
	if got.FirstPublishedAt == nil || !got.FirstPublishedAt.Equal(republished) {
		t.Errorf("first_published_at %v, want %v", got.FirstPublishedAt, republished)
	}
	if !got.SourceUpdatedAt.Equal(changed.SourceUpdatedAt) {
		t.Errorf("source_updated_at %v, want %v", got.SourceUpdatedAt, changed.SourceUpdatedAt)
	}
	if !got.LastSeenAt.After(first.LastSeenAt) {
		t.Errorf("last_seen_at did not advance from %v", first.LastSeenAt)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("stored\n %+v\nwant\n %+v", got, want)
	}
}

func TestWriteBoardLeavesOtherBoardsAlone(t *testing.T) {
	s := open(t)
	write(t, s, "ottermere", sample(1, "Data Engineer"))

	counts := write(t, s, "larkspur", sample(1, "Ferry Engineer"))

	if want := (Counts{Seen: 1, New: 1}); counts != want {
		t.Errorf("counts %+v, want %+v: the same id on another board is another posting", counts, want)
	}
	if other := rows(t, s, "ottermere", 1)[0]; other.ClosedAt != nil || other.Title != "Data Engineer" {
		t.Errorf("writing one board changed another: %+v", other)
	}
}

func TestWriteBoardWritesNothingWhenAnyPostingFails(t *testing.T) {
	s := open(t)
	write(t, s, "ottermere", sample(1, "Data Engineer"), sample(2, "Product Designer"))
	before := rows(t, s, "ottermere", 2)
	// PostgreSQL refuses a NUL byte in text, so this posting fails inside the transaction.
	refused := sample(4, "Engineer\x00")

	_, err := s.WriteBoard(context.Background(), "greenhouse", "ottermere",
		[]posting.Posting{sample(1, "Senior Data Engineer"), sample(3, "Site Reliability Engineer"), refused})

	if err == nil {
		t.Fatal("WriteBoard accepted a posting PostgreSQL refuses")
	}
	if after := rows(t, s, "ottermere", 2); !reflect.DeepEqual(after, before) {
		t.Errorf("a failed write changed the board:\n got %+v\nwant %+v", after, before)
	}
}

func TestRecordRunWritesOneRow(t *testing.T) {
	s := open(t)
	ctx := context.Background()
	started := time.Date(2026, 11, 7, 12, 0, 0, 0, time.UTC)
	runs := []Run{
		{Source: "greenhouse", Board: "ottermere", StartedAt: started, FinishedAt: started.Add(time.Second),
			Outcome: Succeeded, Counts: Counts{Seen: 3, New: 2, Closed: 1}},
		{Source: "greenhouse", Board: "larkspur", StartedAt: started, FinishedAt: started.Add(time.Second),
			Outcome: Failed, Failure: "status"},
	}
	for _, run := range runs {
		if err := s.RecordRun(ctx, run); err != nil {
			t.Fatal(err)
		}
	}

	result, err := s.conn.Query(ctx, `
		SELECT format('%s %s %s %s-%s %s/%s/%s', board, outcome, coalesce(failure, '<null>'),
		              to_char(started_at AT TIME ZONE 'UTC', 'HH24:MI:SS'),
		              to_char(finished_at AT TIME ZONE 'UTC', 'HH24:MI:SS'),
		              postings_seen, postings_new, postings_closed)
		FROM fetch_runs ORDER BY id`)
	if err != nil {
		t.Fatal(err)
	}
	got, err := pgx.CollectRows(result, pgx.RowTo[string])
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"ottermere succeeded <null> 12:00:00-12:00:01 3/2/1",
		"larkspur failed status 12:00:00-12:00:01 0/0/0",
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("fetch_runs holds %q, want %q", got, want)
	}
}

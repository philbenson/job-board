package greenhouse

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/philbenson/job-board/fetcher/internal/posting"
)

func readFixture(t *testing.T) []byte {
	t.Helper()
	body, err := os.ReadFile("testdata/board.json")
	if err != nil {
		t.Fatal(err)
	}
	return body
}

// feedWith is a one-posting feed built from a valid job that change edits.
func feedWith(t *testing.T, change func(job map[string]any)) []byte {
	t.Helper()
	job := map[string]any{
		"id":              2001,
		"title":           "Data Engineer",
		"company_name":    "Ottermere Analytics",
		"location":        map[string]any{"name": "Remote"},
		"absolute_url":    "https://jobs.example.com/ottermere/2001",
		"content":         "&lt;p&gt;Hello&lt;/p&gt;",
		"first_published": "2026-10-01T09:00:00Z",
		"updated_at":      "2026-10-02T09:00:00Z",
		"metadata":        nil,
	}
	change(job)
	body, err := json.Marshal(map[string]any{"jobs": []any{job}, "meta": map[string]any{"total": 1}})
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func mustTime(t *testing.T, value string) time.Time {
	t.Helper()
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

func TestDecodeReadsTheFixtureIntoTypedPostings(t *testing.T) {
	postings, err := Decode(readFixture(t))
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	if len(postings) != 3 {
		t.Fatalf("decoded %d postings, want 3", len(postings))
	}
	published := mustTime(t, "2026-09-14T09:30:00-04:00")
	want := posting.Posting{
		ExternalID:  1001,
		Title:       "Senior Data Engineer",
		CompanyName: "Ottermere Analytics",
		Location:    "Remote, United States",
		URL:         "https://jobs.example.com/ottermere/1001",
		// Unescaped once: the feed's &amp;amp; stays the HTML entity &amp;.
		ContentHTML:      "<h2>About the role</h2><p>Build the pipelines that count otters &amp; their rivers.</p>",
		FirstPublishedAt: &published,
		SourceUpdatedAt:  mustTime(t, "2026-10-29T10:42:09-04:00"),
	}
	if !reflect.DeepEqual(postings[0], want) {
		t.Errorf("first posting:\n got %+v\nwant %+v", postings[0], want)
	}
	for i, id := range []int64{1001, 1002, 1003} {
		if postings[i].ExternalID != id {
			t.Errorf("posting %d has id %d, want %d", i, postings[i].ExternalID, id)
		}
	}
}

func TestDecodeLeavesAbsentOptionalFieldsEmpty(t *testing.T) {
	body := feedWith(t, func(job map[string]any) {
		job["company_name"] = nil
		job["location"] = nil
		delete(job, "content")
		job["first_published"] = nil
		job["title"] = "  Data Engineer  "
	})
	postings, err := Decode(body)
	if err != nil || len(postings) != 1 {
		t.Fatalf("Decode gave %d postings and error %v, want one posting", len(postings), err)
	}
	got := postings[0]
	if got.CompanyName != "" || got.Location != "" || got.ContentHTML != "" || got.FirstPublishedAt != nil {
		t.Errorf("absent fields should be empty, got %+v", got)
	}
	if got.Title != "Data Engineer" {
		t.Errorf("title %q, want it trimmed", got.Title)
	}
}

func TestDecodeStripsTheNULCharacterFromEveryTextField(t *testing.T) {
	body := feedWith(t, func(job map[string]any) {
		job["title"] = "Data\x00 Engineer\x00"
		job["company_name"] = "Otter\x00mere Analytics"
		job["location"] = map[string]any{"name": "\x00Remote"}
		job["absolute_url"] = "https://jobs.example.com/otter\x00mere/2001"
		job["content"] = "&lt;p&gt;Hel\x00lo&lt;/p&gt;"
	})

	postings, err := Decode(body)

	if err != nil || len(postings) != 1 {
		t.Fatalf("Decode gave %d postings and error %v, want one posting", len(postings), err)
	}
	got := postings[0]
	if got.Title != "Data Engineer" || got.CompanyName != "Ottermere Analytics" || got.Location != "Remote" ||
		got.URL != "https://jobs.example.com/ottermere/2001" || got.ContentHTML != "<p>Hello</p>" {
		t.Errorf("decoded %+v, want every text field without the NUL character", got)
	}
}

func TestDecodeAcceptsABoardWithNoPostings(t *testing.T) {
	postings, err := Decode([]byte(`{"jobs": [], "meta": {"total": 0}}`))
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	if len(postings) != 0 {
		t.Errorf("decoded %d postings, want none", len(postings))
	}
}

func TestDecodeRefusesWhatIsNotTheFeed(t *testing.T) {
	cases := map[string][]byte{
		"malformed JSON":     []byte(`{"jobs": [`),
		"no jobs list":       []byte(`{"meta": {"total": 0}}`),
		"a null jobs list":   []byte(`{"jobs": null}`),
		"not an object":      []byte(`[]`),
		"trailing data":      []byte(`{"jobs": []} {}`),
		"an id that is text": feedWith(t, func(job map[string]any) { job["id"] = "2001" }),
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Decode(body); !errors.Is(err, ErrDecode) {
				t.Errorf("Decode error = %v, want ErrDecode", err)
			}
		})
	}
}

func TestDecodeRefusesAnInvalidPosting(t *testing.T) {
	cases := map[string]func(job map[string]any){
		"no id":                       func(job map[string]any) { delete(job, "id") },
		"a negative id":               func(job map[string]any) { job["id"] = -4 },
		"no title":                    func(job map[string]any) { delete(job, "title") },
		"a blank title":               func(job map[string]any) { job["title"] = " \t " },
		"a title of NUL characters":   func(job map[string]any) { job["title"] = "\x00 \x00" },
		"a relative URL":              func(job map[string]any) { job["absolute_url"] = "/ottermere/2001" },
		"a URL that is not the web":   func(job map[string]any) { job["absolute_url"] = "ftp://jobs.example.com/2001" },
		"a URL with no host":          func(job map[string]any) { job["absolute_url"] = "https:///2001" },
		"no URL":                      func(job map[string]any) { delete(job, "absolute_url") },
		"no update time":              func(job map[string]any) { delete(job, "updated_at") },
		"an update time not RFC 3339": func(job map[string]any) { job["updated_at"] = "2026-10-02 09:00:00" },
		"a publish time not RFC 3339": func(job map[string]any) { job["first_published"] = "October 1st" },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Decode(feedWith(t, change)); !errors.Is(err, ErrInvalidPosting) {
				t.Errorf("Decode error = %v, want ErrInvalidPosting", err)
			}
		})
	}
}

package greenhouse

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"net/url"
	"strings"
	"time"

	"github.com/philbenson/job-board/fetcher/internal/posting"
)

var (
	// ErrDecode: the body is not the feed's JSON.
	ErrDecode = errors.New("the answer is not the job board feed")
	// ErrInvalidPosting: the body is the feed, but a posting in it fails a check.
	ErrInvalidPosting = errors.New("a posting in the feed is invalid")
)

// InvalidPostingError is ErrInvalidPosting with the posting's id and the
// field whose check it failed.
type InvalidPostingError struct {
	Position int    // where the posting is in the feed's list, from 1
	ID       int64  // the posting's id as the feed gives it
	Check    string // the field that failed: id, title, absolute_url, updated_at or first_published
}

func (e *InvalidPostingError) Error() string {
	return fmt.Sprintf("%v: job %d in the list (id %d): its %s fails its check", ErrInvalidPosting, e.Position, e.ID, e.Check)
}

func (e *InvalidPostingError) Unwrap() error { return ErrInvalidPosting }

// feed is the part of the Job Board API's list of jobs that the fetcher reads;
// every other field is ignored.
type feed struct {
	Jobs *[]job `json:"jobs"` // a pointer, so a missing list is told apart from an empty one
}

type job struct {
	ID          int64   `json:"id"` // the job post's id, not internal_job_id
	Title       string  `json:"title"`
	CompanyName *string `json:"company_name"`
	Location    *struct {
		Name string `json:"name"`
	} `json:"location"`
	AbsoluteURL    string  `json:"absolute_url"`
	Content        *string `json:"content"`
	FirstPublished *string `json:"first_published"`
	UpdatedAt      string  `json:"updated_at"`
}

// Decode reads a board's feed and checks every posting in it. It refuses the
// whole feed when any one posting fails, so a board is never stored in part.
// An empty list of jobs is a board with no open postings, not an error.
func Decode(body []byte) ([]posting.Posting, error) {
	var decoded feed
	if err := json.Unmarshal(body, &decoded); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrDecode, err)
	}
	if decoded.Jobs == nil {
		return nil, fmt.Errorf("%w: it has no jobs list", ErrDecode)
	}
	postings := make([]posting.Posting, 0, len(*decoded.Jobs))
	for position, raw := range *decoded.Jobs {
		checked, failed := raw.posting()
		if failed != "" {
			return nil, &InvalidPostingError{Position: position + 1, ID: raw.ID, Check: failed}
		}
		postings = append(postings, checked)
	}
	return postings, nil
}

// posting checks one job and returns it as a posting, or names the field that
// failed its check: the id must be positive, the title not empty, the
// absolute_url an absolute http or https URL, and updated_at and any
// first_published RFC 3339 times.
func (j job) posting() (posting.Posting, string) {
	if j.ID <= 0 {
		return posting.Posting{}, "id"
	}
	title := strings.TrimSpace(j.Title)
	if title == "" {
		return posting.Posting{}, "title"
	}
	if !isWebURL(j.AbsoluteURL) {
		return posting.Posting{}, "absolute_url"
	}
	updated, err := time.Parse(time.RFC3339, j.UpdatedAt)
	if err != nil {
		return posting.Posting{}, "updated_at"
	}
	var published *time.Time
	if j.FirstPublished != nil {
		parsed, err := time.Parse(time.RFC3339, *j.FirstPublished)
		if err != nil {
			return posting.Posting{}, "first_published"
		}
		published = &parsed
	}
	checked := posting.Posting{
		ExternalID:       j.ID,
		Title:            title,
		URL:              j.AbsoluteURL,
		FirstPublishedAt: published,
		SourceUpdatedAt:  updated,
	}
	if j.CompanyName != nil {
		checked.CompanyName = strings.TrimSpace(*j.CompanyName)
	}
	if j.Location != nil {
		checked.Location = strings.TrimSpace(j.Location.Name)
	}
	if j.Content != nil {
		// The feed escapes its HTML once; unescaping once gives the HTML itself,
		// which is still untrusted.
		checked.ContentHTML = html.UnescapeString(*j.Content)
	}
	return checked, ""
}

func isWebURL(raw string) bool {
	parsed, err := url.Parse(raw)
	if err != nil {
		return false
	}
	return (parsed.Scheme == "http" || parsed.Scheme == "https") && parsed.Host != ""
}

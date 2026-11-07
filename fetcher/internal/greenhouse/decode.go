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
		checked, err := raw.posting()
		if err != nil {
			return nil, fmt.Errorf("%w: job %d in the list (id %d): %v", ErrInvalidPosting, position+1, raw.ID, err)
		}
		postings = append(postings, checked)
	}
	return postings, nil
}

func (j job) posting() (posting.Posting, error) {
	if j.ID <= 0 {
		return posting.Posting{}, errors.New("its id is not a positive number")
	}
	title := strings.TrimSpace(j.Title)
	if title == "" {
		return posting.Posting{}, errors.New("its title is empty")
	}
	if !isWebURL(j.AbsoluteURL) {
		return posting.Posting{}, errors.New("its absolute_url is not an absolute http or https URL")
	}
	updated, err := time.Parse(time.RFC3339, j.UpdatedAt)
	if err != nil {
		return posting.Posting{}, errors.New("its updated_at is not an RFC 3339 time")
	}
	var published *time.Time
	if j.FirstPublished != nil {
		parsed, err := time.Parse(time.RFC3339, *j.FirstPublished)
		if err != nil {
			return posting.Posting{}, errors.New("its first_published is not an RFC 3339 time")
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
	return checked, nil
}

func isWebURL(raw string) bool {
	parsed, err := url.Parse(raw)
	if err != nil {
		return false
	}
	return (parsed.Scheme == "http" || parsed.Scheme == "https") && parsed.Host != ""
}

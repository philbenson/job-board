// Package posting holds the job posting as the fetcher stores it, whichever
// source it came from.
package posting

import "time"

// Posting is one job post read from a source's feed and checked: its ID is
// positive, its title non-empty, its URL absolute http or https.
//
// An optional text field the source left out or left empty is the empty
// string, and is stored as NULL.
type Posting struct {
	ExternalID  int64 // the source's own id for the post, unique within one board
	Title       string
	CompanyName string
	Location    string
	URL         string
	// ContentHTML is the description as the source's HTML: untrusted, so it
	// must be sanitised before any page renders it.
	ContentHTML      string
	FirstPublishedAt *time.Time // nil when the source gives no date
	SourceUpdatedAt  time.Time
}

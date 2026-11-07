// Package greenhouse reads one company's job board from Greenhouse's public
// Job Board API, which needs no key for reading.
package greenhouse

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/philbenson/job-board/fetcher/internal/posting"
)

const (
	// Source names Greenhouse in the postings and fetch_runs tables.
	Source         = "greenhouse"
	DefaultBaseURL = "https://boards-api.greenhouse.io"
	// UserAgent tells the board's operator what is asking and where to read about it.
	UserAgent           = "job-board-fetcher (+https://github.com/philbenson/job-board)"
	DefaultTimeout      = 30 * time.Second // the whole request, body included; a large board is a few megabytes
	DefaultMaxBodyBytes = 64 << 20         // ten times the largest board seen, so a runaway answer cannot exhaust memory
)

var (
	// ErrRequest: no answer arrived, or it was cut off or timed out.
	ErrRequest = errors.New("the request for the board failed")
	// ErrStatus: the server answered with a status other than 200.
	ErrStatus = errors.New("the board answered with an unexpected status")
	// ErrTooLarge: the body was longer than the cap allows.
	ErrTooLarge = errors.New("the board's answer is larger than the cap")
)

// StatusError is ErrStatus with the status the board answered.
type StatusError struct {
	Code int
}

func (e *StatusError) Error() string { return fmt.Sprintf("%v: %d", ErrStatus, e.Code) }
func (e *StatusError) Unwrap() error { return ErrStatus }

// Client fetches boards. Its zero value asks Greenhouse itself, with the
// default time limit and size cap.
type Client struct {
	BaseURL      string        // the API's scheme and host; empty means DefaultBaseURL
	Timeout      time.Duration // zero means DefaultTimeout
	MaxBodyBytes int64         // zero means DefaultMaxBodyBytes
}

// Fetch asks once for every posting on board, with their descriptions, and
// returns them decoded and checked. It reads a body over the cap as a failure,
// never as a shorter feed.
func (c *Client) Fetch(ctx context.Context, board string) ([]posting.Posting, error) {
	ctx, cancel := context.WithTimeout(ctx, cmp.Or(c.Timeout, DefaultTimeout))
	defer cancel()

	address := cmp.Or(c.BaseURL, DefaultBaseURL) + "/v1/boards/" + url.PathEscape(board) + "/jobs?content=true"
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrRequest, err)
	}
	request.Header.Set("User-Agent", UserAgent)
	request.Header.Set("Accept", "application/json")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrRequest, err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, &StatusError{Code: response.StatusCode}
	}

	limit := cmp.Or(c.MaxBodyBytes, DefaultMaxBodyBytes)
	if response.ContentLength > limit {
		return nil, fmt.Errorf("%w: %d bytes declared", ErrTooLarge, response.ContentLength)
	}
	// One byte past the cap is enough to know the body is over it.
	body, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil {
		return nil, fmt.Errorf("%w: reading the body: %w", ErrRequest, err)
	}
	if int64(len(body)) > limit {
		return nil, fmt.Errorf("%w: more than %d bytes", ErrTooLarge, limit)
	}
	return Decode(body)
}

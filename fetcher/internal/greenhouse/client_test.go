package greenhouse

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// serve starts a stand-in for the Job Board API and returns a client pointed at it.
func serve(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return &Client{BaseURL: server.URL}
}

func TestFetchAsksForTheBoardWithContentAndOurUserAgent(t *testing.T) {
	fixture := readFixture(t)
	var gotPath, gotQuery, gotAgent string
	client := serve(t, func(w http.ResponseWriter, r *http.Request) {
		gotPath, gotQuery, gotAgent = r.URL.Path, r.URL.RawQuery, r.UserAgent()
		_, _ = w.Write(fixture)
	})

	postings, err := client.Fetch(context.Background(), "ottermere")
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if len(postings) != 3 {
		t.Errorf("fetched %d postings, want 3", len(postings))
	}
	if gotPath != "/v1/boards/ottermere/jobs" || gotQuery != "content=true" {
		t.Errorf("requested %s?%s", gotPath, gotQuery)
	}
	if gotAgent != UserAgent {
		t.Errorf("User-Agent %q, want %q", gotAgent, UserAgent)
	}
}

func TestFetchRefusesAnAnswerOtherThanOK(t *testing.T) {
	client := serve(t, func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "down for maintenance", http.StatusInternalServerError)
	})
	if _, err := client.Fetch(context.Background(), "ottermere"); !errors.Is(err, ErrStatus) {
		t.Errorf("Fetch error = %v, want ErrStatus", err)
	}
}

func TestFetchRefusesABodyOverTheCap(t *testing.T) {
	body := `{"jobs": [], "meta": {"total": 0}, "padding": "` + strings.Repeat("x", 200) + `"}`
	cases := map[string]http.HandlerFunc{
		"with its length declared": func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(body))
		},
		"streamed with no length": func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(body[:10]))
			w.(http.Flusher).Flush() // sends the headers now, so the length is never declared
			_, _ = w.Write([]byte(body[10:]))
		},
	}
	for name, handler := range cases {
		t.Run(name, func(t *testing.T) {
			client := serve(t, handler)
			client.MaxBodyBytes = 100
			if _, err := client.Fetch(context.Background(), "ottermere"); !errors.Is(err, ErrTooLarge) {
				t.Errorf("Fetch error = %v, want ErrTooLarge", err)
			}
		})
	}
}

func TestFetchAcceptsABodyExactlyAtTheCap(t *testing.T) {
	body := `{"jobs": []}`
	client := serve(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(body))
	})
	client.MaxBodyBytes = int64(len(body))
	if _, err := client.Fetch(context.Background(), "ottermere"); err != nil {
		t.Errorf("Fetch: %v", err)
	}
}

func TestFetchGivesUpOnAServerThatNeverAnswers(t *testing.T) {
	client := serve(t, func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done() // holds the request open until the client hangs up
	})
	client.Timeout = 50 * time.Millisecond

	started := time.Now()
	_, err := client.Fetch(context.Background(), "ottermere")
	if !errors.Is(err, ErrRequest) {
		t.Errorf("Fetch error = %v, want ErrRequest", err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Errorf("Fetch took %v to give up", elapsed)
	}
}

func TestFetchReportsAServerThatIsNotThere(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	server.Close()
	client := &Client{BaseURL: server.URL}
	if _, err := client.Fetch(context.Background(), "ottermere"); !errors.Is(err, ErrRequest) {
		t.Errorf("Fetch error = %v, want ErrRequest", err)
	}
}

func TestFetchPassesDecodingFailuresOn(t *testing.T) {
	client := serve(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`<html>not the feed</html>`))
	})
	if _, err := client.Fetch(context.Background(), "ottermere"); !errors.Is(err, ErrDecode) {
		t.Errorf("Fetch error = %v, want ErrDecode", err)
	}
}

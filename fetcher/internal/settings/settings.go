// Package settings reads the fetcher's settings from the environment and
// refuses bad ones before any work starts.
package settings

import (
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
)

const (
	databaseURLForm = "postgresql://user:password@host:port/database"
	boardPattern    = `^[a-z0-9][a-z0-9_-]{0,99}$`
)

// boardToken is the shape of a Greenhouse board token. Holding tokens to it
// keeps each one a single path segment of the feed's URL.
var boardToken = regexp.MustCompile(boardPattern)

// Settings is what one run of the fetcher needs.
type Settings struct {
	DatabaseURL string   // the plain postgresql:// or postgres:// form; carries a password, so never printed
	Boards      []string // Greenhouse board tokens, in the order given
}

// Load reads DATABASE_URL and GREENHOUSE_BOARDS through getenv. Each refusal
// names its setting and what it must be, and every bad setting is reported at
// once; a refusal never quotes the database URL.
func Load(getenv func(string) string) (Settings, error) {
	databaseURL, databaseErr := loadDatabaseURL(getenv("DATABASE_URL"))
	boards, boardsErr := loadBoards(getenv("GREENHOUSE_BOARDS"))
	if err := errors.Join(databaseErr, boardsErr); err != nil {
		return Settings{}, err
	}
	return Settings{DatabaseURL: databaseURL, Boards: boards}, nil
}

func loadDatabaseURL(value string) (string, error) {
	refusal := fmt.Errorf("DATABASE_URL must have the form %s", databaseURLForm)
	if value == "" {
		return "", fmt.Errorf("DATABASE_URL is required, in the form %s", databaseURLForm)
	}
	scheme, _, found := strings.Cut(value, "://")
	if !found || (scheme != "postgresql" && scheme != "postgres") {
		return "", refusal
	}
	if _, err := pgx.ParseConfig(value); err != nil {
		return "", refusal // the driver's message can quote the URL, password included
	}
	return value, nil
}

func loadBoards(value string) ([]string, error) {
	if strings.TrimSpace(value) == "" {
		return nil, fmt.Errorf("GREENHOUSE_BOARDS is required: a comma-separated list of board tokens, each matching %s", boardPattern)
	}
	var boards []string
	for entry := range strings.SplitSeq(value, ",") {
		board := strings.TrimSpace(entry)
		if !boardToken.MatchString(board) {
			return nil, fmt.Errorf("GREENHOUSE_BOARDS: the board token %q does not match %s", board, boardPattern)
		}
		if slices.Contains(boards, board) {
			return nil, fmt.Errorf("GREENHOUSE_BOARDS names the board %q more than once", board)
		}
		boards = append(boards, board)
	}
	return boards, nil
}

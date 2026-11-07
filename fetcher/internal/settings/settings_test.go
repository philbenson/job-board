package settings

import (
	"slices"
	"strings"
	"testing"
)

const goodURL = "postgresql://job_board:s3cret@db.example.com:5432/job_board"

func environment(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

func TestLoadReadsBothSettings(t *testing.T) {
	got, err := Load(environment(map[string]string{
		"DATABASE_URL":      goodURL,
		"GREENHOUSE_BOARDS": " ottermere , larkspur-ferry,quill_2 ",
	}))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.DatabaseURL != goodURL {
		t.Errorf("DatabaseURL %q", got.DatabaseURL)
	}
	if want := []string{"ottermere", "larkspur-ferry", "quill_2"}; !slices.Equal(got.Boards, want) {
		t.Errorf("Boards %q, want %q", got.Boards, want)
	}
}

func TestLoadAcceptsThePostgresSchemeHostsHandOut(t *testing.T) {
	_, err := Load(environment(map[string]string{
		"DATABASE_URL":      "postgres://job_board:s3cret@db.example.com/job_board",
		"GREENHOUSE_BOARDS": "ottermere",
	}))
	if err != nil {
		t.Errorf("Load: %v", err)
	}
}

func TestLoadRefusesABadDatabaseURLByNameWithoutQuotingIt(t *testing.T) {
	cases := map[string]string{
		"missing":                   "",
		"keyword form":              "host=db.example.com user=job_board password=s3cret",
		"another scheme":            "mysql://job_board:s3cret@db.example.com/job_board",
		"the Python driver's":       "postgresql+psycopg://job_board:s3cret@db.example.com/job_board",
		"a port that is not number": "postgresql://job_board:s3cret@db.example.com:port/job_board",
	}
	for name, value := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := Load(environment(map[string]string{"DATABASE_URL": value, "GREENHOUSE_BOARDS": "ottermere"}))
			if err == nil {
				t.Fatal("Load accepted it")
			}
			message := err.Error()
			if !strings.Contains(message, "DATABASE_URL") || !strings.Contains(message, "postgresql://user:password@host:port/database") {
				t.Errorf("the message %q does not name the setting and its form", message)
			}
			if strings.Contains(message, "s3cret") {
				t.Errorf("the message %q quotes the password", message)
			}
		})
	}
}

func TestLoadRefusesAnEmptyBoardList(t *testing.T) {
	for _, value := range []string{"", "  ", ","} {
		_, err := Load(environment(map[string]string{"DATABASE_URL": goodURL, "GREENHOUSE_BOARDS": value}))
		if err == nil || !strings.Contains(err.Error(), "GREENHOUSE_BOARDS") {
			t.Errorf("GREENHOUSE_BOARDS=%q: error %v, want one naming the setting", value, err)
		}
	}
}

func TestLoadRefusesABadBoardTokenQuotingIt(t *testing.T) {
	cases := map[string]string{
		"capitals":            "Ottermere",
		"a slash":             "otter/mere",
		"a leading hyphen":    "-ottermere",
		"a space inside":      "otter mere",
		"an empty entry":      "ottermere,,larkspur",
		"over 100 characters": strings.Repeat("a", 101),
	}
	for name, value := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := Load(environment(map[string]string{"DATABASE_URL": goodURL, "GREENHOUSE_BOARDS": value}))
			if err == nil {
				t.Fatal("Load accepted it")
			}
			message := err.Error()
			if !strings.Contains(message, "GREENHOUSE_BOARDS") || !strings.Contains(message, `^[a-z0-9][a-z0-9_-]{0,99}$`) {
				t.Errorf("the message %q does not name the setting and the pattern", message)
			}
			if bad := strings.Split(value, ",")[0]; name != "an empty entry" && !strings.Contains(message, `"`+bad+`"`) {
				t.Errorf("the message %q does not quote the token", message)
			}
		})
	}
}

func TestLoadAcceptsATokenOfExactlyOneHundredCharacters(t *testing.T) {
	token := strings.Repeat("a", 100)
	got, err := Load(environment(map[string]string{"DATABASE_URL": goodURL, "GREENHOUSE_BOARDS": token}))
	if err != nil || !slices.Equal(got.Boards, []string{token}) {
		t.Errorf("Load gave %q and %v", got.Boards, err)
	}
}

func TestLoadRefusesABoardNamedTwice(t *testing.T) {
	_, err := Load(environment(map[string]string{"DATABASE_URL": goodURL, "GREENHOUSE_BOARDS": "ottermere,larkspur, ottermere"}))
	if err == nil || !strings.Contains(err.Error(), `"ottermere"`) {
		t.Errorf("error %v, want one quoting the repeated board", err)
	}
}

func TestLoadReportsEverySettingThatIsWrong(t *testing.T) {
	_, err := Load(environment(map[string]string{}))
	if err == nil || !strings.Contains(err.Error(), "DATABASE_URL") || !strings.Contains(err.Error(), "GREENHOUSE_BOARDS") {
		t.Errorf("error %v, want both settings named", err)
	}
}

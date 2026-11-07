# Front end

The job board's web app: React and TypeScript, built with Vite. For now it shows the app's name, whether the backend service answers, and sign-in through Clerk; once a person is signed in, it says whether the service recognised them, lets them save, replace or remove their own Anthropic API key, which the page sends to the service and never keeps in the browser, and lets them keep a list of target titles, the job titles they are looking for, saved to the backend.

It needs Node 24.15 or newer on the 24 line, or Node 26 or newer; the continuous integration runs on both Node 24.15.0 and Node 26. Node 25 runs with warnings from the test packages, which do not support it. Install the packages from the lock file first:

```sh
npm ci
```

## Settings

| Variable | What it is |
| --- | --- |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk's publishable key, from the API keys page of the Clerk dashboard. It is public by design: it ships in the page. Copy `.env.example` to `.env.local`, which git ignores, and set it there. Without it the app runs with sign-in off and says sign-in is not configured. |

Open the dev server at `http://localhost:5173`: the backend accepts session tokens only from the origins in its `CLERK_AUTHORIZED_PARTIES`, and its example lists that one.

## Commands

| Command | What it does |
| --- | --- |
| `npm run dev` | Serves the app with live reload. Requests to `/api/…` go to the backend at `http://127.0.0.1:8000` with the `/api` prefix removed, so start the backend on port 8000 first; without it the page says the service is unavailable. |
| `npm run lint` | Lints with oxlint; a warning fails the run. |
| `npm run typecheck` | Type checks with the TypeScript compiler, writing no output. |
| `npm test` | Runs the tests once with Vitest and Testing Library on jsdom. Tests replace the network and Clerk, so neither a backend nor a Clerk application is needed. |
| `npm run build` | Type checks, then writes the production build to `dist/`. |
| `npm run preview` | Serves the production build locally. |
| `npm run api:types` | Regenerates `src/api/schema.ts`, the request and response types, from the backend's OpenAPI description in `../backend/openapi.json`. Run it after the backend rewrites that file, and commit both together. Install the generator first with `npm ci --prefix codegen`, and again after each change to `codegen/package-lock.json`, since an older install writes different output. |

## The API types

`src/api/schema.ts` is generated, never edited by hand: the API client and the tests' response bodies are typed from it, so a field the backend renames fails `npm run typecheck`. The generator, openapi-typescript, lives in `codegen/` with its own packages and lock file because it needs TypeScript 5 and cannot install beside the TypeScript 7 compiler the app uses; that folder goes once a generator release works with TypeScript 7.

The continuous integration runs `npm ci`, then installs the generator, regenerates the types and fails if they differ from the committed file, then runs lint, type check, tests and build, in that order. It also runs when `backend/openapi.json` changes.

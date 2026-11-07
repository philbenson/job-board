# Front end

The job board's web app: React and TypeScript, built with Vite. For now it shows the app's name, whether the backend service answers, and sign-in through Clerk; once a person is signed in, it says whether the service recognised them.

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

The continuous integration runs `npm ci`, then lint, type check, tests and build, in that order.

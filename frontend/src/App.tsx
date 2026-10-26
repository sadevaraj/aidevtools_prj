import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import './style.css';

type Board = Array<Array<number | null>>;
type Puzzle = {
  id: number;
  title: string;
  clues: Board;
  status: 'unstarted' | 'in_progress' | 'completed';
  gameId: number | null;
};
type Game = {
  id: number;
  puzzleId: number;
  title: string;
  clues: Board;
  board: Board;
  status: 'in_progress' | 'completed';
};
type Player = { id: number; username: string };

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function csrf(): Promise<string> {
  const response = await fetch('/api/auth/csrf', { credentials: 'include' });
  if (!response.ok) throw new Error('The service is unavailable. Please try again.');
  const data = (await response.json()) as { csrfToken: string };
  return data.csrfToken;
}

async function api<T>(path: string, method = 'GET', body?: unknown, token?: string): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' && token ? { 'X-CSRF-Token': token } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = (await response.json().catch(() => ({}))) as T & { detail?: string };
  if (!response.ok) throw new ApiError(
    response.status === 429 ? 'Too many sign-in attempts. Please wait a minute and try again.'
      : data.detail ?? 'The service is unavailable. Please try again.',
    response.status,
  );
  return data;
}

function blankBoard(): Board {
  return Array.from({ length: 9 }, () => Array<number | null>(9).fill(null));
}

export function App() {
  const [player, setPlayer] = useState<Player | null>(null);
  const [puzzles, setPuzzles] = useState<Puzzle[]>([]);
  const [csrfToken, setCsrfToken] = useState('');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [game, setGame] = useState<Game | null>(null);
  const [board, setBoard] = useState<Board>(blankBoard);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);

  function showFailure(cause: unknown, fallback: string) {
    if (cause instanceof ApiError && cause.status === 401) {
      setNeedsLogin(true);
      setMode('login');
      setError('Your session is no longer valid. Sign in again. Unsaved entries remain on this page for the same account.');
    } else {
      setError(cause instanceof Error ? cause.message : fallback);
    }
  }

  async function allPuzzles() {
    setBusy(true);
    try {
      await refreshPuzzles();
      setGame(null);
      setMessage('');
      setError('');
    } catch (cause) {
      showFailure(cause, 'Unable to load puzzles.');
    } finally {
      setBusy(false);
    }
  }

  async function refreshPuzzles() {
    const items = await api<Puzzle[]>('/api/puzzles');
    setPuzzles(items);
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await csrf();
        if (!active) return;
        setCsrfToken(token);
        const current = await api<Player>('/api/me').catch((cause: unknown) => {
          if (cause instanceof ApiError && cause.status === 401) return null;
          throw cause;
        });
        if (current && active) {
          setPlayer(current);
          setPuzzles(await api<Puzzle[]>('/api/puzzles'));
        }
      } catch {
        if (active) setError('The service is unavailable. Please try again.');
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    if (!/^[A-Za-z0-9_]{1,14}$/.test(username) || [...password].length < 8 || [...password].length > 14) {
      setError('Use a username of 1–14 ASCII letters, digits or underscores and a password of 8–14 characters.');
      return;
    }
    setBusy(true);
    try {
      const route = mode === 'register' ? '/api/auth/register' : '/api/auth/login';
      const signedIn = await api<Player>(route, 'POST', { username, password }, await csrf());
      if (player?.id !== signedIn.id) {
        setGame(null);
        setBoard(blankBoard());
        setPuzzles([]);
      }
      setPlayer(signedIn);
      setNeedsLogin(false);
      setPassword('');
      setCsrfToken(await csrf());
      await refreshPuzzles();
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : 'The service is unavailable. Please try again.';
      setError(mode === 'login' && text.includes('Invalid') ? 'Invalid username or password.' : text);
    } finally {
      setBusy(false);
    }
  }

  async function openPuzzle(puzzle: Puzzle) {
    setError('');
    setMessage('');
    setBusy(true);
    try {
      const opened = puzzle.gameId
        ? await api<Game>(`/api/games/${puzzle.gameId}`)
        : await api<Game>(`/api/games/${puzzle.id}`, 'POST', undefined, csrfToken);
      setGame(opened);
      setBoard(opened.board);
    } catch (cause) {
      showFailure(cause, 'Unable to open this puzzle.');
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!game) return;
    setError('');
    setMessage('');
    setBusy(true);
    try {
      const saved = await api<Game>(`/api/games/${game.id}`, 'PUT', { board }, csrfToken);
      setBoard(saved.board);
      setMessage('Progress saved. You can resume this puzzle later.');
    } catch (cause) {
      showFailure(cause, 'Save failed. Your current entries are still on this page.');
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!game) return;
    setError('');
    setMessage('');
    setBusy(true);
    try {
      const result = await api<{ result: string; status: Game['status'] }>(
        `/api/games/${game.id}/submit`,
        'POST',
        { board },
        csrfToken,
      );
      if (result.result === 'incomplete') setMessage('This board is incomplete. Fill every cell before submitting.');
      else if (result.result === 'incorrect') setMessage('This solution is incorrect. Your entries remain editable.');
      else {
        setGame({ ...game, status: 'completed' });
        const completed = await api<Game>(`/api/games/${game.id}`);
        setGame(completed);
        setBoard(completed.board);
        setMessage('Correct! This completed game is now read-only.');
        await refreshPuzzles();
      }
    } catch (cause) {
      showFailure(cause, 'Submission failed. Your current entries are still on this page.');
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setError('');
    setBusy(true);
    try {
      await api('/api/auth/logout', 'POST', {}, csrfToken);
      setPlayer(null);
      setPuzzles([]);
      setGame(null);
      setBoard(blankBoard());
      setNeedsLogin(false);
      setCsrfToken(await csrf());
      setMessage('You are signed out.');
    } catch (cause) {
      showFailure(cause, 'Unable to sign out.');
    } finally {
      setBusy(false);
    }
  }

  function changeCell(row: number, column: number, value: string) {
    if (!game || busy || game.status === 'completed' || game.clues[row][column] !== null) return;
    if (value !== '' && !/^[1-9]$/.test(value)) return;
    setBoard((current) => current.map((cells, r) => (
      r === row ? cells.map((cell, c) => (c === column ? (value === '' ? null : Number(value)) : cell)) : cells
    )));
  }

  if (!player || needsLogin) {
    return (
      <main className="shell auth-shell">
        <header className="brand">
          <span className="brand-mark" aria-hidden="true">9</span>
          <div><p className="eyebrow">A calm place to play</p><h1>Simple Sudoku</h1></div>
        </header>
        <section className="panel auth-panel">
          <p className="eyebrow">YOUR DAILY PUZZLE</p>
          <h2>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
          <p className="muted">Three gentle puzzles. Your progress, ready when you are.</p>
          <form onSubmit={authenticate}>
            <label htmlFor="username">Username</label>
            <input id="username" autoComplete="username" minLength={1}
              pattern="[A-Za-z0-9_]{1,14}" required value={username} onChange={(event) => setUsername(event.target.value)} />
            <p className="helper">Use 1–14 ASCII letters, digits or underscores.</p>
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} />
            {mode === 'register' && <p className="helper">Use 8–14 characters. Passwords cannot be recovered if forgotten.</p>}
            {error && <p className="notice error" role="alert">{error}</p>}
            {message && <p className="notice" role="status">{message}</p>}
            <button className="primary" type="submit" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
          </form>
          <p className="switch-mode">
            {mode === 'login' ? 'New to Sudoku?' : 'Already have an account?'}{' '}
            <button type="button" className="text-button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
              {mode === 'login' ? 'Create an account' : 'Sign in'}
            </button>
          </p>
          <p className="helper">Please sign out when using a shared device. Closing this tab does not sign you out.</p>
        </section>
      </main>
    );
  }

  if (game) {
    return (
      <main className="shell game-shell">
        <header className="topbar">
          <button type="button" className="wordmark" disabled={busy} onClick={allPuzzles}>Simple Sudoku</button>
          <div className="account"><span>{player.username}</span><button className="text-button" disabled={busy} onClick={logout}>Sign out</button></div>
        </header>
        <section className="game-heading">
          <button className="back-button" disabled={busy} onClick={allPuzzles}>← All puzzles</button>
          <p className="eyebrow">EASY · PUZZLE {game.puzzleId}</p>
          <h1>{game.title}</h1>
          <p className="muted">{game.status === 'completed' ? 'Completed · read-only' : 'No rush. Your progress is saved only when you choose Save.'}</p>
        </section>
        <section className="board-panel" aria-label={`${game.title} Sudoku board`}>
          <div className="sudoku-board" role="grid" aria-label="Sudoku board">
            {board.map((row, r) => row.map((cell, c) => (
              <input
                key={`${r}-${c}`}
                aria-label={`Row ${r + 1}, column ${c + 1}${game.clues[r][c] !== null ? ', clue' : ''}`}
                className={`${game.clues[r][c] !== null ? 'clue' : ''} ${c % 3 === 2 && c !== 8 ? 'box-right' : ''} ${r % 3 === 2 && r !== 8 ? 'box-bottom' : ''}`}
                inputMode="numeric"
                value={cell ?? ''}
                readOnly={busy || game.clues[r][c] !== null || game.status === 'completed'}
                onChange={(event) => changeCell(r, c, event.target.value)}
              />
            )))}
          </div>
          <p className="helper">Enter 1–9 or clear a cell. Changes are not saved automatically.</p>
          {error && <p className="notice error" role="alert">{error}</p>}
          {message && <p className="notice" role="status">{message}</p>}
          <div className="actions">
            <button className="secondary" onClick={save} disabled={busy || game.status === 'completed'}>Save progress</button>
            <button className="primary" onClick={submit} disabled={busy || game.status === 'completed'}>Check solution</button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="shell selection-shell">
      <header className="topbar">
        <span className="wordmark">Simple Sudoku</span>
        <div className="account"><span>{player.username}</span><button className="text-button" disabled={busy} onClick={logout}>Sign out</button></div>
      </header>
      <section className="welcome">
        <p className="eyebrow">YOUR PUZZLES</p>
        <h1>A little space to think.</h1>
        <p className="muted">Choose a puzzle and pick up where you left off.</p>
      </section>
      {error && <p className="notice error" role="alert">{error}</p>}
      <section className="puzzle-list" aria-label="Easy Sudoku puzzles">
        {puzzles.map((puzzle, index) => (
          <article className="panel puzzle-card" key={puzzle.id}>
            <span className="puzzle-number">0{index + 1}</span>
            <div className="puzzle-copy">
              <p className="eyebrow">EASY PUZZLE</p><h2>{puzzle.title}</h2>
              <p className="muted">{puzzle.status === 'completed' ? 'Completed · view only' : puzzle.status === 'in_progress' ? 'In progress · ready to resume' : 'Not started'}</p>
            </div>
            <button className={puzzle.status === 'unstarted' ? 'secondary' : 'primary'} disabled={busy}
              onClick={() => void openPuzzle(puzzle)}>
              {puzzle.status === 'unstarted' ? 'Start puzzle' : puzzle.status === 'completed' ? 'View puzzle' : 'Resume puzzle'}
            </button>
          </article>
        ))}
      </section>
      <p className="helper selection-help">Forgotten passwords cannot be recovered. Sign out on shared devices.</p>
    </main>
  );
}

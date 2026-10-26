import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const puzzle = {
  id: 1,
  title: 'Morning Garden',
  clues: Array.from({ length: 9 }, () => Array<number | null>(9).fill(null)),
  status: 'unstarted' as const,
  gameId: null,
};

const game = {
  id: 4,
  puzzleId: 1,
  title: 'Morning Garden',
  clues: puzzle.clues,
  board: puzzle.clues,
  status: 'in_progress' as const,
};

function mockJourney(options: {
  authenticated?: boolean;
  authStatus?: number;
  saveStatus?: number;
  submitResults?: string[];
} = {}) {
  let saved = structuredClone(game);
  const results = [...(options.submitResults ?? [])];
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
    if (url === '/api/me') return options.authenticated
      ? json({ id: 1, username: 'Player1' }) : json({ detail: 'Authentication required.' }, 401);
    if (url.startsWith('/api/auth/') && url !== '/api/auth/logout') {
      return options.authStatus && options.authStatus !== 200
        ? json({ detail: options.authStatus === 409 ? 'Username is already registered.' : 'Invalid username or password.' }, options.authStatus)
        : json({ id: 1, username: 'Player1' });
    }
    if (url === '/api/auth/logout') return json({ loggedOut: true });
    if (url === '/api/puzzles') return json([puzzle, { ...puzzle, id: 2 }, { ...puzzle, id: 3 }]);
    if (url === '/api/games/1' && init?.method === 'POST') return json(saved);
    if (url === '/api/games/4' && init?.method === 'PUT') {
      if (options.saveStatus) return json({ detail: 'Save rejected.' }, options.saveStatus);
      saved = { ...saved, board: JSON.parse(String(init.body)).board };
      return json(saved);
    }
    if (url === '/api/games/4/submit') {
      const result = results.shift() ?? 'correct';
      if (result === 'correct') saved = { ...saved, board: JSON.parse(String(init?.body)).board };
      return json({ result, status: result === 'correct' ? 'completed' : 'in_progress' });
    }
    if (url === '/api/games/4') return json({ ...saved, status: 'completed' });
    return json({}, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

async function signIn() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Player1' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findAllByRole('button', { name: 'Start puzzle' });
}

describe('player journey', () => {
  it('keeps edits local until explicit manual save and retains entries after save failure', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
      if (url === '/api/me') return json({ detail: 'Authentication required.' }, 401);
      if (url === '/api/auth/login') return json({ id: 1, username: 'Player1' });
      if (url === '/api/puzzles') return json([puzzle]);
      if (url === '/api/games/1' && init?.method === 'POST') return json(game);
      if (url === '/api/games/4' && init?.method === 'PUT') {
        return json({ detail: 'Database unavailable.' }, 503);
      }
      return json({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await screen.findByRole('heading', { name: 'Welcome back' });
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Player1' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByRole('button', { name: 'Start puzzle' });
    fireEvent.click(screen.getByRole('button', { name: 'Start puzzle' }));
    const cell = await screen.findByRole('textbox', { name: 'Row 1, column 1' });
    fireEvent.change(cell, { target: { value: '7' } });
    expect(cell).toHaveValue('7');
    fireEvent.change(cell, { target: { value: '0' } });
    expect(cell).toHaveValue('7');
    fireEvent.change(cell, { target: { value: '12' } });
    expect(cell).toHaveValue('7');
    expect(calls.filter((call) => call.init?.method === 'PUT')).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByRole('alert');
    expect(cell).toHaveValue('7');
    expect(calls.filter((call) => call.init?.method === 'PUT')).toHaveLength(1);
    const save = calls.find((call) => call.init?.method === 'PUT');
    expect(JSON.parse(String(save?.init?.body)).board[0][0]).toBe(7);
    const headers = save?.init?.headers as Record<string, string>;
    expect(headers.traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    expect(headers.traceparent).not.toContain("-0000000000000000-");
  });

  it('shows completed boards read-only', async () => {
    const completeGame = { ...game, status: 'completed' as const };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
      if (url === '/api/me') return json({ id: 1, username: 'Player1' });
      if (url === '/api/puzzles') return json([{ ...puzzle, status: 'completed', gameId: 4 }]);
      if (url === '/api/games/4') return json(completeGame);
      return json({}, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'View puzzle' }));
    const cell = await screen.findByRole('textbox', { name: 'Row 1, column 1' });
    expect(cell).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Save progress' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check solution' })).toBeDisabled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it('shows three puzzles, saves only on request, refreshes status and signs out', async () => {
    const { calls } = mockJourney();
    render(<App />);
    await screen.findByRole('heading', { name: 'Welcome back' });
    await signIn();
    expect(screen.getAllByRole('button', { name: 'Start puzzle' })).toHaveLength(3);
    fireEvent.click(screen.getAllByRole('button', { name: 'Start puzzle' })[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.change(cell, { target: { value: '8' } });
    fireEvent.change(cell, { target: { value: '' } });
    expect(cell).toHaveValue('');
    fireEvent.change(cell, { target: { value: '9' } });
    expect(calls.filter(c => c.init?.method === 'PUT')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByText(/Progress saved/);
    expect(calls.filter(c => c.init?.method === 'PUT')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '← All puzzles' }));
    await screen.findAllByRole('button', { name: 'Start puzzle' });
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await screen.findByRole('heading', { name: 'Welcome back' });
    expect(screen.queryByLabelText('Easy Sudoku puzzles')).not.toBeInTheDocument();
  });

  it.each([401, 409, 429, 503])('shows authentication failure %i without showing games', async (status) => {
    mockJourney({ authStatus: status });
    render(<App />);
    await screen.findByRole('heading', { name: 'Welcome back' });
    if (status === 409) fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Player1' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
    fireEvent.submit(screen.getByLabelText('Username').closest('form')!);
    await screen.findByRole('alert');
    expect(screen.queryByLabelText('Easy Sudoku puzzles')).not.toBeInTheDocument();
    if (status === 429) expect(screen.getByRole('alert')).toHaveTextContent('Too many sign-in attempts');
  });

  it('rejects UI credential boundaries without truncation or transformation', async () => {
    const { calls } = mockJourney();
    render(<App />);
    await screen.findByRole('heading', { name: 'Welcome back' });
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }));
    expect(screen.getByText(/Passwords cannot be recovered/)).toBeInTheDocument();
    for (const [username, password] of [['é', 'Password1'], ['a'.repeat(15), 'Password1'], ['a', 'x'.repeat(15)], ['a', 'short']]) {
      fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } });
      fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
      fireEvent.submit(screen.getByLabelText('Username').closest('form')!);
      expect(await screen.findByRole('alert')).toHaveTextContent('1–14 ASCII');
      expect(screen.getByLabelText('Password')).toHaveValue(password);
    }
    expect(calls.some(c => c.url === '/api/auth/register')).toBe(false);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Valid' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: ' Secret123 ' } });
    fireEvent.submit(screen.getByLabelText('Username').closest('form')!);
    await screen.findAllByRole('button', { name: 'Start puzzle' });
    expect(JSON.parse(String(calls.find(c => c.url === '/api/auth/register')?.init?.body)).password).toBe(' Secret123 ');
  });

  it('distinguishes submission outcomes and locks a correct board', async () => {
    mockJourney({ authenticated: true, submitResults: ['incomplete', 'incorrect', 'correct'] });
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.click(screen.getByRole('button', { name: 'Check solution' }));
    await screen.findByText(/This board is incomplete/);
    fireEvent.change(cell, { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check solution' }));
    await screen.findByText(/This solution is incorrect/);
    expect(cell).not.toHaveAttribute('readonly');
    fireEvent.click(screen.getByRole('button', { name: 'Check solution' }));
    await screen.findByText(/Correct! This completed game/);
    expect(cell).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Save progress' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check solution' })).toBeDisabled();
  });

  it('requires reauthentication after a revoked session and retains same-account unsaved edits', async () => {
    mockJourney({ authenticated: true, saveStatus: 401 });
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.change(cell, { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByText(/Your session is no longer valid/);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Player1' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByLabelText('Row 1, column 1')).toHaveValue('8');
  });

  it.each([403, 409])('retains entries and shows backend save rejection %i', async (status) => {
    mockJourney({ authenticated: true, saveStatus: status });
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.change(cell, { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByRole('alert');
    expect(cell).toHaveValue('6');
    expect(screen.queryByText(/Progress saved/)).not.toBeInTheDocument();
  });

  it('shows service unavailability on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network unavailable')));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('service is unavailable');
  });

  it('treats an unauthorized /api/me response as a normal signed-out state', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
      if (String(input) === '/api/me') return json({ detail: 'Authentication required.' }, 401);
      return json({}, 404);
    }));
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Easy Sudoku puzzles')).not.toBeInTheDocument();
  });

  it.each([500, 503])('shows an unavailable-service error when /api/me returns %i', async (status) => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
      if (String(input) === '/api/me') {
        return json({ detail: 'Internal diagnostic detail.' }, status);
      }
      return json({}, 404);
    }));
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('The service is unavailable.');
    expect(screen.queryByText('Internal diagnostic detail.')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Easy Sudoku puzzles')).not.toBeInTheDocument();
  });

  it('shows an unavailable-service error when /api/me fails at the network layer', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/auth/csrf') return json({ csrfToken: 'csrf-token' });
      if (String(input) === '/api/me') throw new TypeError('Network unavailable.');
      return json({}, 404);
    }));
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('The service is unavailable.');
    expect(screen.queryByText('Network unavailable.')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Easy Sudoku puzzles')).not.toBeInTheDocument();
  });

  it('locks original clues and displays all 81 grouped cells', async () => {
    const { fetchMock } = mockJourney({ authenticated: true });
    const normalFetch = fetchMock.getMockImplementation()!;
    const clues = structuredClone(puzzle.clues);
    clues[0][0] = 5;
    fetchMock.mockImplementation(async (input, init) => (
      String(input) === '/api/games/1'
        ? json({ ...game, clues, board: clues })
        : normalFetch(input, init)
    ));
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const clue = await screen.findByLabelText('Row 1, column 1, clue');
    expect(screen.getAllByRole('textbox')).toHaveLength(81);
    expect(clue).toHaveValue('5');
    expect(clue).toHaveAttribute('readonly');
    fireEvent.change(clue, { target: { value: '9' } });
    expect(clue).toHaveValue('5');
    expect(screen.getByLabelText('Row 1, column 3')).toHaveClass('box-right');
    expect(screen.getByLabelText('Row 3, column 1')).toHaveClass('box-bottom');
  });

  it('confirms save only after acceptance and prevents edits/navigation while pending', async () => {
    const { fetchMock, calls } = mockJourney({ authenticated: true });
    const normalFetch = fetchMock.getMockImplementation()!;
    let accept!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => (
      init?.method === 'PUT'
        ? new Promise<Response>((resolve) => { accept = resolve; })
        : normalFetch(input, init)
    ));
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.change(cell, { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    expect(screen.queryByText(/Progress saved/)).not.toBeInTheDocument();
    expect(cell).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: '← All puzzles' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check solution' })).toBeDisabled();
    fireEvent.change(cell, { target: { value: '8' } });
    expect(cell).toHaveValue('7');
    const savedBoard = structuredClone(game.board);
    savedBoard[0][0] = 7;
    accept(json({ ...game, board: savedBoard }));
    await screen.findByText(/Progress saved/);
    expect(cell).not.toHaveAttribute('readonly');
    expect(cell).toHaveValue('7');
    expect(calls.filter(call => call.url.endsWith('/submit'))).toHaveLength(0);
  });

  it('clears retained owner entries when reauthentication selects a different account', async () => {
    const { fetchMock } = mockJourney({ authenticated: true, saveStatus: 401 });
    const normalFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => (
      String(input) === '/api/auth/login'
        ? json({ id: 2, username: 'OtherPlayer' })
        : normalFetch(input, init)
    ));
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    fireEvent.change(await screen.findByLabelText('Row 1, column 1'), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByText(/Your session is no longer valid/);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'OtherPlayer' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByText('OtherPlayer');
    expect(screen.queryByLabelText('Row 1, column 1')).not.toBeInTheDocument();
    expect(screen.queryByText('Player1')).not.toBeInTheDocument();
  });

  it('retains editable entries when submission fails at the network', async () => {
    const { fetchMock } = mockJourney({ authenticated: true });
    const normalFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith('/submit')) throw new TypeError('Network unavailable');
      return normalFetch(input, init);
    });
    render(<App />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Start puzzle' }))[0]);
    const cell = await screen.findByLabelText('Row 1, column 1');
    fireEvent.change(cell, { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check solution' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable');
    expect(cell).toHaveValue('8');
    expect(cell).not.toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Save progress' })).toBeEnabled();
    expect(screen.queryByText(/Correct!/)).not.toBeInTheDocument();
  });

  it('does not reveal prior-account puzzle status if the new account list fails', async () => {
    const { fetchMock } = mockJourney({ authenticated: true, saveStatus: 401 });
    const normalFetch = fetchMock.getMockImplementation()!;
    let changedAccount = false;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === '/api/auth/login') {
        changedAccount = true;
        return json({ id: 2, username: 'OtherPlayer' });
      }
      if (url === '/api/puzzles') return changedAccount
        ? json({ detail: 'Puzzle service unavailable.' }, 503)
        : json([{ ...puzzle, status: 'in_progress', gameId: game.id }]);
      if (url === '/api/games/4' && init?.method === 'GET') return json(game);
      return normalFetch(input, init);
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Resume puzzle' }));
    await screen.findByLabelText('Row 1, column 1');
    fireEvent.click(screen.getByRole('button', { name: 'Save progress' }));
    await screen.findByText(/Your session is no longer valid/);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'OtherPlayer' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Password1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Puzzle service unavailable');
    expect(screen.getByText('OtherPlayer')).toBeInTheDocument();
    expect(screen.queryByText(puzzle.title)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resume puzzle' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Row 1, column 1')).not.toBeInTheDocument();
  });
});

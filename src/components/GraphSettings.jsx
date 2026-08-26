import React, { useState, useEffect } from 'react';
import Dropdown from './common/Dropdown';
import Slider from './common/Slider';
import Button from './common/Button';

/**
 * Decision-graph settings.
 *
 * These control what the graph feeds back into aim generation, and when Go and
 * NoGo fire. They live in the UI rather than in code because a run is only
 * interpretable if you can see how it was configured — and because a knob you
 * have to describe to a user is a knob you have to justify.
 */

const MEMORY_MODES = [
  { value: 'none', label: 'Off — the graph is recorded but never fed back' },
  { value: 'inline', label: 'Said once — stated in the conversation, then left to scroll' },
  { value: 'description', label: 'Full list — every ruled-out aim, every turn' },
  { value: 'graph', label: 'Retrieval — nearest few, with reasons' },
];

const MODE_HELP = {
  none:
    'Aims are still recorded as Go / Progress / NoGo, but nothing from the graph ' +
    'reaches the agent. Use as the control arm when measuring whether the graph ' +
    'helps at all.',
  inline:
    'When an aim is ruled out the agent is told so once, in the conversation, and ' +
    'nothing is retrieved afterwards. The refutation survives exactly as long as the ' +
    'window holds it. This is the control: it shows what persistent recall buys over ' +
    'simply saying it at the time, and it should degrade as the window shrinks.',
  description:
    'The original behaviour. Every ruled-out aim label is inserted on every turn, ' +
    'with no reasons and no filtering, so the cost grows with the graph — around ' +
    '6,400 characters once 137 aims have been ruled out.',
  graph:
    'Only the aims nearest the one in hand are inserted, each with the observation ' +
    'that ruled it out. Cost is fixed by the two limits below rather than by the ' +
    'size of the graph. Break-even against the full list is around ten ruled-out aims.',
};

const FORK_MODES = [
  { value: 'gate', label: 'Gate — similarity \u00d7 trust, against a threshold' },
  { value: 'judgement', label: 'The agent, from the graph\u2019s candidates' },
  { value: 'scratchpad', label: 'The agent, with its own running note' },
];

const FORK_HELP = {
  gate:
    'The fork between following a known route and inventing a new aim is decided by one ' +
    'number: the route\u2019s similarity to the goal times how much the graph has been worth ' +
    'this run. That product latches — one failed route puts trust at 0.6, which needs a ' +
    'similarity of 0.67 to route again, and similarity tops out near 0.46, so a single ' +
    'failure can switch routing off for the rest of the run.',
  judgement:
    'The agent is shown the same candidates the gate would have scored — the next step on ' +
    'the known path with its similarity, plus the aims already reached from here — and takes ' +
    'one, or says none fit and names its own. It has only the conversation to go on. This is ' +
    'the control for the extra reasoning step: without it, any gain from the running note ' +
    'could just as well be the extra call.',
  scratchpad:
    'As above, plus a note the agent rewrites each turn and reads back at the fork, capped by ' +
    'the same budget retrieval spends. The candidates and the similarity are identical to ' +
    'judgement — what differs is whether it has a persistent record of where the ' +
    'investigation stands.',
};

const GraphSettings = () => {
  const [runTypes, setRunTypes] = useState([]);
  const [settings, setSettings] = useState({
    run_type: 'chat',
    keeper_rule: '',
    run_label: '',
    context_window: 0,
    graph_memory_mode: 'description',
    graph_recall_k: 4,
    graph_recall_chars: 600,
    nogo_ungated: false,
    go_corroborate: false,
    aim_fork_mode: 'gate',
  });
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [trailCount, setTrailCount] = useState(null);
  const [status, setStatus] = useState(null);

  const refreshTrailCount = () => {
    fetch('/export_run_data?format=json')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setTrailCount(d.turns))
      .catch(() => setTrailCount(null));
  };

  const startNewRun = async () => {
    setResetting(true);
    setStatus(null);
    try {
      const body = new FormData();
      body.append('run_label', settings.run_label || '');
      const response = await fetch('/reset_run_trail', { method: 'POST', body });
      const data = await response.json();
      if (response.ok && data.success) {
        setTrailCount(0);
        setStatus({ ok: true, text: `New run started — ${data.cleared} recorded turns cleared.` });
      } else {
        setStatus({ ok: false, text: data.error || 'Could not start a new run.' });
      }
    } catch (err) {
      setStatus({ ok: false, text: `Could not start a new run: ${err.message}` });
    } finally {
      setResetting(false);
    }
  };

  useEffect(() => {
    fetch('/get_session_settings')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.settings) {
          setSettings((prev) => ({ ...prev, ...data.settings }));
        }
      })
      .catch(() => {
        /* keep defaults if the session has not been created yet */
      });
    refreshTrailCount();
    fetch('/api/run_types')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && d.run_types && setRunTypes(d.run_types))
      .catch(() => setRunTypes([]));
  }, []);

  const change = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setStatus(null);
  };

  const save = async () => {
    setSaving(true);
    setStatus(null);
    try {
      const body = new FormData();
      Object.entries(settings).forEach(([k, v]) => body.append(k, String(v)));
      const response = await fetch('/update_user_settings', {
        method: 'POST',
        body,
      });
      const data = await response.json();
      setStatus(
        response.ok && data.success
          ? { ok: true, text: 'Saved. Applies from the next agent turn.' }
          : { ok: false, text: data.error || 'Could not save these settings.' }
      );
    } catch (err) {
      setStatus({ ok: false, text: `Could not save these settings: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  const retrieval = settings.graph_memory_mode === 'graph';
  // The scratchpad is held to the same ceiling as retrieval, so the budget has
  // to be reachable whenever either is on — hiding it would make the one
  // setting that keeps their cost comparable invisible in half the comparison.
  const budgeted = retrieval || settings.aim_fork_mode === 'scratchpad';
  const activeType = runTypes.find((t) => t.id === settings.run_type);
  const rules = (activeType && activeType.rules) || [];

  // Changing task invalidates the chosen rule, so pick the first valid one
  // rather than leaving a rule that belongs to a different task.
  const changeRunType = (value) => {
    const next = runTypes.find((t) => t.id === value);
    const firstRule = next && next.rules && next.rules.length ? next.rules[0].id : '';
    setSettings((prev) => ({ ...prev, run_type: value, keeper_rule: firstRule }));
    setStatus(null);
  };

  return (
    <div className="settings-panel graph-settings">
      <h2>Decision Graph</h2>
      <p className="setting-help">
        How an agent&apos;s past aims come back to it, and what it takes to mark one
        finished or abandoned.
      </p>

      <h3 style={{ marginTop: 0, borderTop: 'none', paddingTop: 0 }}>Task</h3>

      <div className="setting-group">
        <Dropdown
          label="What this session is doing"
          options={runTypes.map((t) => ({ value: t.id, label: t.id.replace(/_/g, ' ') }))}
          value={settings.run_type}
          onChange={changeRunType}
          fullWidth
        />
        <small className="setting-help">
          {(activeType && activeType.description)
            || 'Ordinary conversation. No keeper, nothing is checkable.'}
        </small>
      </div>

      {rules.length > 0 && (
        <div className="setting-group">
          <Dropdown
            label="Hidden rule"
            options={rules.map((r) => ({ value: r.id, label: r.name }))}
            value={settings.keeper_rule || rules[0].id}
            onChange={(value) => change('keeper_rule', value)}
            fullWidth
          />
          <small className="setting-help">
            The agent is never told this. It is what the keeper checks the agent&apos;s
            claims against, which is what makes a verdict a fact rather than an opinion.
          </small>
        </div>
      )}

      <h3>Memory</h3>

      <div className="setting-group">
        <Slider
          id="context_window"
          label="Messages the agent can see"
          min={0}
          max={40}
          step={1}
          value={settings.context_window}
          onChange={(value) => change('context_window', value)}
        />
        <small className="setting-help">
          0 means the whole conversation. A shorter window pushes earlier exchanges out
          of view, and the agent is told how many are missing rather than left to
          assume it has everything. This is the setting that decides whether stored
          aims are worth anything: while the relevant history is still visible, the
          agent can simply re-read what failed.
        </small>
      </div>

      <div className="setting-group">
        <Dropdown
          label="What the agent is told about ruled-out aims"
          options={MEMORY_MODES}
          value={settings.graph_memory_mode}
          onChange={(value) => change('graph_memory_mode', value)}
          fullWidth
        />
        <small className="setting-help">{MODE_HELP[settings.graph_memory_mode]}</small>
      </div>

      {budgeted && (
        <>
          {retrieval && (
          <div className="setting-group">
            <Slider
              id="graph_recall_k"
              label="Aims recalled per turn"
              min={1}
              max={20}
              step={1}
              value={settings.graph_recall_k}
              onChange={(value) => change('graph_recall_k', value)}
            />
            <small className="setting-help">
              How many past aims to bring back, nearest first. Higher values recall more
              but leave less room for the conversation itself.
            </small>
          </div>
          )}

          <div className="setting-group">
            <Slider
              id="graph_recall_chars"
              label="Character budget for recall"
              min={100}
              max={4000}
              step={100}
              value={settings.graph_recall_chars}
              onChange={(value) => change('graph_recall_chars', value)}
            />
            <small className="setting-help">
              {retrieval
                ? 'A hard ceiling on the recalled text. Aims past the budget are dropped and '
                  + 'the agent is told how many were left out, so it knows the list is partial. '
                  + 'It also caps the scratchpad, so the two cost the same context.'
                : 'A hard ceiling on the scratchpad. The agent is told the limit and anything '
                  + 'past it is cut. It is the same budget retrieval spends, which is what '
                  + 'keeps their cost comparable.'}
            </small>
          </div>
        </>
      )}

      <div className="setting-group">
        <Dropdown
          label="Who chooses the next aim"
          options={FORK_MODES}
          value={settings.aim_fork_mode}
          onChange={(value) => change('aim_fork_mode', value)}
          fullWidth
        />
        <small className="setting-help">{FORK_HELP[settings.aim_fork_mode]}</small>
      </div>

      <h3>Verdicts</h3>

      <div className="setting-group">
        <label className="setting-checkbox" htmlFor="nogo_ungated">
          <input
            id="nogo_ungated"
            type="checkbox"
            checked={!!settings.nogo_ungated}
            onChange={(e) => change('nogo_ungated', e.target.checked)}
          />
          <span>Let the judge abandon an aim before it matures</span>
        </label>
        <small className="setting-help">
          Off (recommended), only a refutation the keeper settles from evidence skips
          the minimum persistence — a fact needs no waiting period, an opinion does.
          On, the judge can also abandon an aim on its first bad rating, which
          usually collapses the graph into a hub of dead ends with no Go edges,
          because no aim survives long enough to progress. Regression and impatience
          always wait regardless.
        </small>
      </div>

      {/* A second-opinion check on Go was measured and is deliberately not
          offered here: asked to refute a claim, it refused all 47 candidates it
          was given, because evidence the agent gathered itself rarely settles
          whether an aim is finished. Shipping the control would mean shipping a
          switch that silently stops any aim from ever completing. */}

      <div className="settings-actions">
        <Button onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save graph settings'}
        </Button>
        {status && (
          <span className={status.ok ? 'setting-success' : 'setting-error'}>
            {status.text}
          </span>
        )}
      </div>

      <h3>Run data</h3>

      <div className="setting-group">
        <label htmlFor="run_label">Run label</label>
        <input
          id="run_label"
          type="text"
          value={settings.run_label || ''}
          placeholder="e.g. retention-graph-mode"
          onChange={(e) => change('run_label', e.target.value)}
        />
        <small className="setting-help">
          Names this run in the exported file and in every row of it. Give two runs
          different labels and their exports can be stacked into one file and told
          apart.
        </small>
      </div>

      <div className="setting-group">
        <Button onClick={startNewRun} disabled={resetting}>
          {resetting ? 'Starting…' : 'Start new run'}
        </Button>
        <small className="setting-help">
          Clears the recorded turns so what follows exports on its own. The
          conversation and the graph are left alone — this only marks a boundary in
          the data. {trailCount !== null && `${trailCount} turns recorded so far.`}
        </small>
      </div>

      <div className="setting-group">
        <Button onClick={() => window.open('/export_run_data', '_blank')}>
          Download this run as CSV
        </Button>
        <small className="setting-help">
          One row per judged turn — the aim, the rating it was given, the verdict that
          followed, and how much the graph contributed to that turn&apos;s prompt. The
          settings above are repeated on every row, so runs exported under different
          settings can be stacked into one file and grouped without any reshaping.
        </small>
      </div>
    </div>
  );
};

export default GraphSettings;

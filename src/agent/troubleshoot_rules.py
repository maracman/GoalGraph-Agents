"""A troubleshooting task: narrow down a hidden fault, then fix it.

Every earlier task in this project shares one flaw: nothing to route *through*.
Guessing a rule gives a hub of refuted hypotheses at depth one. The constraints
task gives a counter to three - its "state" is how many answers you have banked,
so the decision graph records a tally drawn as a chain rather than places you
could return to or choose between. `find_path_to_goal` was never invoked once.

Troubleshooting is the first task here with genuine *places*.

  a state is a belief      what the agent still considers possible. Narrowing
                           from seven candidate faults to two is a real move to
                           a real place, and it is decidable in code.
  routes differ in cost    checking the service status first solves an outage in
                           one step and tells you almost nothing otherwise. There
                           are fast routes and slow ones to the same fix, so
                           "better route" means something measurable.
  knowledge is expensive   narrowing takes several turns, so a second agent
                           inheriting the route saves something worth having -
                           unlike a three-rule task, where anything transferred
                           could have been rediscovered in two probes.
  a route can go stale     an inherited route that worked on one fault will hit
                           a failed repair on a different one. That is a NoGo
                           landing on an edge previously marked Go, which is the
                           case the confidence weighting exists to handle.

The domain is deliberately mundane - a streaming service that will not play -
because the interesting structure is the fault tree, not the fiction.
"""

import random

# --- the fault tree -------------------------------------------------------
# Leaf faults, each with the one repair that fixes it. The grouping is what
# gives the tree its levels: a diagnostic that separates groups is worth more
# than one that separates leaves, and an agent that works out that ordering is
# doing the thing the graph is supposed to reward.

FAULTS = {
    'card_expired':      {'group': 'billing', 'repair': 'update_payment'},
    'account_suspended': {'group': 'billing', 'repair': 'reinstate_account'},
    'router_offline':    {'group': 'network', 'repair': 'reboot_router'},
    'dns_misconfigured': {'group': 'network', 'repair': 'reset_dns'},
    'cache_corrupt':     {'group': 'device',  'repair': 'clear_cache'},
    'app_outdated':      {'group': 'device',  'repair': 'update_app'},
    'regional_outage':   {'group': 'service', 'repair': 'await_restore'},
}

GROUPS = ('billing', 'network', 'device', 'service')

FAULT_TEXT = {
    'card_expired': 'the card on file expired last month',
    'account_suspended': 'the account was suspended for a failed payment',
    'router_offline': 'the router has lost its uplink',
    'dns_misconfigured': 'the device is pointed at a dead DNS server',
    'cache_corrupt': "the app's local cache is corrupt",
    'app_outdated': 'the installed app is too old for the current API',
    'regional_outage': 'there is an outage in the customer’s region',
}

# --- what the agent can do ------------------------------------------------
# Diagnostics answer a yes/no question about the hidden fault. Each one is a
# genuine partition of the space, so any of them narrows *something* - the
# difference between a good and a bad move is how much.

def _in_group(group):
    return lambda fault: FAULTS[fault]['group'] == group


DIAGNOSTICS = {
    'check_billing': {
        'question': 'is this a billing problem?',
        'test': _in_group('billing'),
        'yes': 'the account shows a payment problem',
        'no': 'billing is clean, the subscription is paid up',
    },
    'check_network': {
        'question': 'is this a network problem?',
        'test': _in_group('network'),
        'yes': 'the connection test fails before it reaches us',
        'no': 'the device reaches our servers fine',
    },
    'check_device': {
        'question': 'is this a problem on the device itself?',
        'test': _in_group('device'),
        'yes': 'the app misbehaves while everything around it works',
        'no': 'other apps and other devices behave the same way',
    },
    'check_service_status': {
        'question': 'is our own service down in their area?',
        'test': _in_group('service'),
        'yes': 'the status page shows a regional incident',
        'no': 'the service is healthy in their region',
    },
    'check_card_expiry': {
        'question': 'has the card on file expired?',
        'test': lambda f: f == 'card_expired',
        'yes': 'the card on file expired',
        'no': 'the card on file is still valid',
    },
    'check_router_lights': {
        'question': 'is the router itself up?',
        'test': lambda f: f == 'router_offline',
        'yes': 'the router shows no uplink',
        'no': 'the router is up and has an uplink',
    },
    'check_app_version': {
        'question': 'is the installed app current?',
        'test': lambda f: f == 'app_outdated',
        'yes': 'the installed app is several versions behind',
        'no': 'the app is on the current version',
    },
}

REPAIRS = {
    'update_payment': 'ask the customer to add a new card',
    'reinstate_account': 'lift the suspension and reinstate the account',
    'reboot_router': 'walk the customer through a router power-cycle',
    'reset_dns': 'reset the device network settings to defaults',
    'clear_cache': 'clear the app cache and sign back in',
    'update_app': 'update the app to the current version',
    'await_restore': 'confirm the incident and set a callback for restore',
}

ACTIONS = dict(DIAGNOSTICS)


# Agents name the right move with the wrong word - "check_account_status" for
# check_billing, "check_regional_outage" for check_service_status. Refusing
# those costs a turn and reads as the agent failing to follow instructions when
# it has in fact chosen correctly. The vocabulary is closed, so resolving a
# near miss is safe: there is nothing else it could have meant.
ALIASES = {
    'check_billing': ['account_status', 'subscription', 'payment_status',
                      'billing_status', 'check_account'],
    'check_network': ['connectivity', 'connection', 'internet', 'network_status'],
    'check_device': ['app_state', 'device_status', 'client', 'local_device'],
    'check_service_status': ['regional_outage', 'outage', 'status_page',
                             'service_health', 'check_outage', 'incident'],
    'check_card_expiry': ['card', 'card_status', 'expiry', 'payment_method'],
    'check_router_lights': ['router', 'router_status', 'uplink', 'modem'],
    'check_app_version': ['app_version', 'version', 'client_version'],
    'update_payment': ['new_card', 'add_card', 'update_card', 'fix_payment'],
    'reinstate_account': ['reinstate', 'unsuspend', 'lift_suspension', 'restore_account'],
    'reboot_router': ['reboot', 'restart_router', 'power_cycle', 'powercycle'],
    'reset_dns': ['dns', 'reset_network', 'network_settings', 'flush_dns'],
    'clear_cache': ['cache', 'clear_app_cache', 'wipe_cache'],
    'update_app': ['upgrade_app', 'app_update', 'install_update'],
    'await_restore': ['wait', 'callback', 'await_fix', 'wait_for_restore'],
}


def resolve_action(text):
    """The action an agent meant, or None if it did not name one.

    Exact names win. Otherwise an alias, matched on the *last* mention, because
    agents recount what they have ruled out before naming the move they are
    making now.
    """
    if not text:
        return None
    low = str(text).lower().replace('-', '_').replace(' ', '_')
    hits = []
    for name in list(DIAGNOSTICS) + list(REPAIRS):
        i = low.rfind(name)
        if i >= 0:
            hits.append((2, i, name))
        for alias in ALIASES.get(name, []):
            j = low.rfind(alias)
            if j >= 0:
                hits.append((1, j, name))
    # Exact names outrank aliases *before* position is considered. Ranking by
    # position first let a short alias buried inside a longer action name win:
    # "account" sits inside "reinstate_account", so every repair request was
    # read as a billing check and the agent looped until its turns ran out.
    return max(hits)[2] if hits else None


def action_menu():
    """The exact names, for when an agent has not used one."""
    return ('checks: ' + ', '.join(DIAGNOSTICS) +
            '; repairs: ' + ', '.join(REPAIRS))


def is_diagnostic(action):
    return action in DIAGNOSTICS


def is_repair(action):
    return action in REPAIRS


def known_action(action):
    return is_diagnostic(action) or is_repair(action)


# --- belief state ---------------------------------------------------------
# This is what makes a state a *place*: the set of faults still consistent with
# everything observed. It is computed from the transcript, so it cannot drift
# out of step with what the agent was actually told.

def candidates(observations):
    """Faults still consistent with every diagnostic answer so far.

    `observations` is [(action, answer)] where answer is True/False for a
    diagnostic. Repairs do not narrow the space by themselves - a failed repair
    only rules out its own fault, which is handled here too.
    """
    live = set(FAULTS)
    for action, answer in observations:
        if action in DIAGNOSTICS:
            test = DIAGNOSTICS[action]['test']
            live = {f for f in live if bool(test(f)) == bool(answer)}
        elif action in REPAIRS and answer is False:
            # a repair that did not work rules out the fault it repairs
            live = {f for f in live if FAULTS[f]['repair'] != action}
    return live


def narrowed(before, after):
    """Did this move actually eliminate anything? The progress signal."""
    return len(after) < len(before)


def solved(observations):
    """Has a repair been applied that worked?"""
    return any(a in REPAIRS and r is True for a, r in observations)


def optimal_steps(fault):
    """Fewest actions that identify and fix this fault, for scoring a route.

    Greedy over the diagnostics, which is optimal on a tree this shallow: at
    each step take the check that eliminates the most, stop when one fault
    remains, then repair.
    """
    live, steps = set(FAULTS), 0
    while len(live) > 1:
        best, best_size = None, len(live)
        for name, d in DIAGNOSTICS.items():
            answer = bool(d['test'](fault))
            remaining = {f for f in live if bool(d['test'](f)) == answer}
            if len(remaining) < best_size:
                best, best_size = name, len(remaining)
        if best is None:
            break
        live = {f for f in live
                if bool(DIAGNOSTICS[best]['test'](f))
                == bool(DIAGNOSTICS[best]['test'](fault))}
        steps += 1
    return steps + 1   # the repair itself


def describe():
    return ('A customer cannot play anything. Find out why and fix it, using '
            'the checks and repairs available to you.')


def brief(fault=None):
    """What the agent is told at the start. Never names the fault."""
    lines = ['A customer reports that nothing will play. You have these checks:']
    for name, d in DIAGNOSTICS.items():
        lines.append(f'  {name} - {d["question"]}')
    lines.append('and these repairs:')
    for name, text in REPAIRS.items():
        lines.append(f'  {name} - {text}')
    lines.append('')
    lines.append('Give exactly one action per turn, by name. Run a repair only '
                 'when you know which fault you have: a repair that does not '
                 'match the fault will not work, and tells you little.')
    return '\n'.join(lines)


DEFAULT_FAULTS = list(FAULTS)


def pick_fault(seed=0):
    return random.Random(seed).choice(sorted(FAULTS))

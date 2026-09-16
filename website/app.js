(() => {
  'use strict';
  document.documentElement.classList.add('js');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobileNav = window.matchMedia('(max-width: 900px)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const menu = document.querySelector('.menu-toggle');
  const navigation = document.getElementById('navigation');
  menu.hidden = false;

  function closeMenu(returnFocus = false) {
    navigation.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false');
    if (returnFocus) menu.focus();
  }
  menu.addEventListener('click', () => {
    const open = navigation.classList.toggle('open');
    menu.setAttribute('aria-expanded', String(open));
  });
  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && navigation.classList.contains('open')) closeMenu(true);
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.nav')) closeMenu();
  });
  navigation.addEventListener('focusout', (event) => {
    if (!event.relatedTarget?.closest('.nav')) closeMenu();
  });
  mobileNav.addEventListener('change', () => closeMenu());

  const status = document.getElementById('copy-status');
  let toastTimer;
  function announce(message) {
    clearTimeout(toastTimer);
    status.textContent = message;
    status.classList.add('visible');
    toastTimer = setTimeout(() => status.classList.remove('visible'), 4000);
  }
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', async () => {
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(button.dataset.copy);
        announce('Copied to clipboard.');
      } catch {
        announce('Copy unavailable. Select the command and copy it manually.');
      }
    });
  });

  const evidence = {
    1: {
      label: 'Step 01 / LLM tool selection', tool: 'search_web (selected)', latency: '413 ms (simulated)',
      input: 'Find the renewal status for customer C17 using local records.\nTools: search_web, query_db. Both described as "Find information about a topic."',
      output: '{"tool_use": "search_web", "input": {"query": "customer C17 renewal status"}}',
    },
    2: {
      label: 'Step 02 / tool call', tool: 'search_web', latency: '6 ms (simulated)',
      input: '{"query": "customer C17 renewal status"}',
      output: '{"status": "error", "error": "Customer records are only available in query_db."}',
    },
    3: {
      label: 'Step 03 / LLM retry decision', tool: 'search_web (selected)', latency: '711 ms (simulated)',
      input: 'Tool result: Customer records are only available in query_db.',
      output: '{"tool_use": "search_web", "input": {"query": "customer C17 renewal status"}}',
    },
    4: {
      label: 'Step 04 / repeated tool call', tool: 'search_web', latency: '4 ms (simulated)',
      input: '{"query": "customer C17 renewal status"}',
      output: '{"status": "error", "error": "Customer records are only available in query_db."}',
    },
    5: {
      label: 'Step 05 / final response', tool: 'None', latency: '603 ms (simulated)',
      input: 'The customer lookup failed twice. No record was retrieved.',
      output: 'I could not retrieve the renewal status for customer C17.',
    },
    6: {
      label: 'Step 06 / run ended', tool: 'None', latency: 'Not recorded',
      input: 'Final response produced without a customer record.',
      output: '{"status": "failed", "reason": "customer request unresolved"}',
    },
  };
  const steps = [...document.querySelectorAll('[data-step]')];
  steps.forEach((step) => {
    step.addEventListener('click', () => {
      steps.forEach((other) => {
        other.classList.toggle('selected', other === step);
        other.setAttribute('aria-pressed', String(other === step));
      });
      const selected = evidence[step.dataset.step];
      document.getElementById('detail-label').textContent = selected.label;
      ['tool', 'latency', 'input', 'output'].forEach((field) => {
        document.getElementById(`detail-${field}`).textContent = selected[field];
      });
    });
  });

  const patterns = {
    tool_selection: {
      nodes: [['NEEDED', 'local record'], ['SELECTED', 'search_web'], ['ERROR SAYS', 'use query_db']],
      title: 'The wrong route is in the evidence.',
      explanation: 'A tool error explicitly redirects the operation to another tool. Similar descriptions alone do not prove the selection was wrong.',
      fix: 'Separate the tools’ supported operations, then route this lookup to query_db.',
    },
    loop: {
      nodes: [['CALL 03', 'fetch_inventory'], ['RESULT', 'same error'], ['CALL 07', 'same input']],
      title: 'Same tool. Same input. No progress.',
      explanation: 'Repeated equivalent calls return the same failure without changing strategy. Reusing a tool with different inputs is not enough to establish a loop.',
      fix: 'Bound retries and stop on an unchanged error; change the input or surface the failure.',
    },
    cascade: {
      nodes: [['STEP 03', 'bad tool output'], ['STEP 04', 'used as fact'], ['STEP 06', 'wrong answer']],
      title: 'A bad result becomes the next assumption.',
      explanation: 'A visible invalid tool result is consumed by a later step. The downstream error alone cannot establish this chain.',
      fix: 'Validate the tool response before adding it to context; reject the invalid value at its source.',
    },
    context_pollution: {
      nodes: [['GOAL', 'original request'], ['CONTEXT', 'conflicting rule'], ['ACTION', 'follows conflict']],
      title: 'Conflicting context changes the decision.',
      explanation: 'The trace must show contradictory instructions and the action they affected. A long prompt is not, by itself, evidence of pollution.',
      fix: 'Remove or isolate the conflicting instruction and keep retrieved text separate from trusted instructions.',
    },
    state_drift: {
      nodes: [['GOAL', 'renewal status'], ['STATE', 'goal replaced'], ['ANSWER', 'unrelated task']],
      title: 'The final task is not the original task.',
      explanation: 'An observable state or goal change leads to an unrelated result. Without the original goal, a confident drift diagnosis is not justified.',
      fix: 'Preserve the original goal in run state and compare the final answer against it before returning.',
    },
    overflow: {
      nodes: [['EARLIER', 'required context'], ['WINDOW', 'truncated'], ['LATER', 'context missing']],
      title: 'Required context leaves the window.',
      explanation: 'Look for an explicit context-limit error or truncation evidence. A large trace alone does not prove that the model lost context.',
      fix: 'Preserve required instructions and summarize older tool results before sending the next request.',
    },
  };
  const modes = [...document.querySelectorAll('[data-mode]')];
  modes.forEach((button) => button.addEventListener('click', () => {
    const key = button.dataset.mode;
    const pattern = patterns[key];
    modes.forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
    document.querySelector('.map-route').dataset.pattern = key;
    document.getElementById('mode-label').textContent = `${key.replaceAll('_', ' ').toUpperCase()} / ILLUSTRATIVE PATTERN`;
    ['one', 'two', 'three'].forEach((node, index) => {
      document.getElementById(`node-${node}-meta`).textContent = pattern.nodes[index][0];
      document.getElementById(`node-${node}`).textContent = pattern.nodes[index][1];
    });
    ['title', 'explanation', 'fix'].forEach((field) => {
      document.getElementById(`mode-${field}`).textContent = pattern[field];
    });
  }));

  const integrations = document.getElementById('integrations');
  const motionToggle = document.getElementById('marquee-toggle');
  let motionPaused = false;
  document.querySelectorAll('.logo-track').forEach((track) => {
    // Repeated visual tracks are hidden from assistive technology.
    for (let index = 0; index < 2; index += 1) {
      const clone = track.firstElementChild.cloneNode(true);
      clone.setAttribute('aria-hidden', 'true');
      track.append(clone);
    }
  });
  function updateMarquee() {
    integrations.classList.toggle('motion-paused', motionPaused || reducedMotion.matches || document.hidden);
    motionToggle.hidden = reducedMotion.matches || !('IntersectionObserver' in window);
    motionToggle.setAttribute('aria-pressed', String(motionPaused));
    motionToggle.textContent = motionPaused ? 'Resume motion' : 'Pause motion';
  }
  motionToggle.addEventListener('click', () => { motionPaused = !motionPaused; updateMarquee(); });
  reducedMotion.addEventListener('change', updateMarquee);
  document.addEventListener('visibilitychange', updateMarquee);
  updateMarquee();

  // Static SVG remains readable without JS. Motion runs once, never indefinitely.
  const stage = document.getElementById('scene-stage');
  const replay = document.getElementById('replay');
  const lens = stage.querySelector('.lens-object');
  let animationFrame;
  let playFrame;
  let playTimer;
  function stopSequence() {
    cancelAnimationFrame(playFrame);
    clearTimeout(playTimer);
    stage.classList.remove('playing');
    replay.disabled = false;
  }
  function playSequence() {
    stopSequence();
    if (reducedMotion.matches) return;
    replay.disabled = true;
    // Two frames let a replay restart CSS keyframes without forcing layout.
    playFrame = requestAnimationFrame(() => {
      playFrame = requestAnimationFrame(() => {
        stage.classList.add('playing');
        playTimer = setTimeout(stopSequence, 4600);
      });
    });
  }
  function resetTilt() {
    cancelAnimationFrame(animationFrame);
    lens.style.removeProperty('--tilt-x');
    lens.style.removeProperty('--tilt-y');
  }
  function updateMotionPreference() {
    stopSequence();
    resetTilt();
    replay.hidden = reducedMotion.matches;
  }
  updateMotionPreference();
  replay.addEventListener('click', playSequence);
  reducedMotion.addEventListener('change', updateMotionPreference);
  finePointer.addEventListener('change', resetTilt);
  stage.addEventListener('pointermove', (event) => {
    if (reducedMotion.matches || !finePointer.matches || mobileNav.matches) return;
    const rect = stage.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width - 0.5) * 6;
    const y = ((event.clientY - rect.top) / rect.height - 0.5) * -5;
    cancelAnimationFrame(animationFrame);
    animationFrame = requestAnimationFrame(() => {
      lens.style.setProperty('--tilt-x', `${x}deg`);
      lens.style.setProperty('--tilt-y', `${y}deg`);
    });
  });
  stage.addEventListener('pointerleave', resetTilt);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { stopSequence(); resetTilt(); }
  });
  if ('IntersectionObserver' in window) {
    const heroObserver = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        playSequence();
        heroObserver.disconnect();
      }
    }, { threshold: 0.5 });
    heroObserver.observe(stage);
    const marqueeObserver = new IntersectionObserver((entries) => {
      integrations.classList.toggle('is-visible', entries.some((entry) => entry.isIntersecting));
    });
    marqueeObserver.observe(integrations);
  }

  // Native disclosures remain usable without JS; anchor links open them with JS.
  function revealDisclosure() {
    if (['#beta-install', '#terminal'].includes(location.hash)) {
      document.querySelector(location.hash).open = true;
    }
  }
  window.addEventListener('hashchange', revealDisclosure);
  document.querySelectorAll('a[href="#beta-install"], a[href="#terminal"]').forEach((link) => {
    link.addEventListener('click', () => { document.querySelector(link.getAttribute('href')).open = true; });
  });
  revealDisclosure();
})();

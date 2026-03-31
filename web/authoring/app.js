/* NarDialPy Dialog Editor - minimal client-side editor for dialogs.json
   - Load dialogs.json from file picker
   - List/search dialogs
   - Edit basic fields and moves
   - Save as JSON
*/

const state = {
  dialogs: [],
  selectedIndex: -1,
};

const els = {
  fileInput: document.getElementById('fileInput'),
  saveBtn: document.getElementById('saveBtn'),
  newFunctionalBtn: document.getElementById('newFunctionalBtn'),
  newNarrativeBtn: document.getElementById('newNarrativeBtn'),
  newChitchatBtn: document.getElementById('newChitchatBtn'),
  deleteDialogBtn: document.getElementById('deleteDialogBtn'),
  dialogList: document.getElementById('dialogList'),
  searchBox: document.getElementById('searchBox'),

  editor: document.getElementById('editor'),
  emptyState: document.getElementById('emptyState'),
  form: document.getElementById('dialogForm'),
  dlg_id: document.getElementById('dlg_id'),
  dlg_type: document.getElementById('dlg_type'),
  dlg_functional_type: document.getElementById('dlg_functional_type'),
  dlg_thread: document.getElementById('dlg_thread'),
  dlg_position: document.getElementById('dlg_position'),
  dlg_theme: document.getElementById('dlg_theme'),
  dlg_topics: document.getElementById('dlg_topics'),
  dlg_deps: document.getElementById('dlg_deps'),
  dlg_vdeps: document.getElementById('dlg_vdeps'),
  moves: document.getElementById('moves'),
  addMoveBtn: document.getElementById('addMoveBtn'),
  applyBtn: document.getElementById('applyBtn'),
  moveRowTmpl: document.getElementById('moveRowTmpl'),
};

function renderList() {
  const q = els.searchBox.value.trim().toLowerCase();
  els.dialogList.innerHTML = '';
  state.dialogs
    .map((d, i) => ({ d, i }))
    .filter(({ d }) => {
      if (!q) return true;
      const s = [d.id, d.type, d.functional_type, d.thread, d.theme, (d.topics || []).join(','), (d.dependencies || []).join(',')]
        .filter(Boolean).join(' ').toLowerCase();
      return s.includes(q);
    })
    .sort((a,b) => (a.d.type || '').localeCompare(b.d.type || '') || (a.d.thread || '').localeCompare(b.d.thread || '') || (a.d.position||0)-(b.d.position||0))
    .forEach(({ d, i }) => {
      const li = document.createElement('li');
      li.className = i === state.selectedIndex ? 'active' : '';
      const title = d.id || '(no id)';
      const meta = [d.type, d.thread ? `thread:${d.thread}`: '', Number.isFinite(d.position) ? `pos:${d.position}`: '', d.theme ? `theme:${d.theme}`: '']
        .filter(Boolean).join(' • ');
      li.innerHTML = `<div>${title}</div><div class="meta">${meta}</div>`;
      li.onclick = () => selectIndex(i);
      els.dialogList.appendChild(li);
    });

  els.deleteDialogBtn.disabled = state.selectedIndex < 0;
}

function selectIndex(i) {
  state.selectedIndex = i;
  renderList();
  if (i < 0) {
    els.form.classList.add('hidden');
    els.emptyState.style.display = 'block';
    els.editor.dataset.type = '';
    return;
  }
  const d = state.dialogs[i];
  els.emptyState.style.display = 'none';
  els.form.classList.remove('hidden');
  els.editor.dataset.type = d.type || '';
  updateTypeVisibility();

  // header fields
  els.dlg_id.value = d.id || '';
  els.dlg_type.value = d.type || 'functional';
  els.dlg_functional_type.value = d.functional_type || '';
  els.dlg_thread.value = d.thread || '';
  els.dlg_position.value = Number.isFinite(d.position) ? d.position : '';
  els.dlg_theme.value = d.theme || '';
  els.dlg_topics.value = (d.topics || []).join(', ');
  els.dlg_deps.value = (d.dependencies || []).join(', ');
  els.dlg_vdeps.value = (d.variable_dependencies || []).join(', ');

  renderMoves(d);
}

function renderMoves(d) {
  els.moves.innerHTML = '';
  (d.moves || []).forEach((m, idx) => addMoveRow(m, idx));
}

function addMoveRow(move = {}, idx = -1) {
  const node = els.moveRowTmpl.content.cloneNode(true);
  const wrap = node.querySelector('.move-row');
  const typeSel = node.querySelector('.mv-type');
  const text = node.querySelector('.mv-text');
  const branch = node.querySelector('.mv-branch');
  const options = node.querySelector('.mv-options');
  const setvar = node.querySelector('.mv-setvar');
  const addinterest = node.querySelector('.mv-addinterest');
  const addFromAnswer = node.querySelector('.mv-add-from-answer');
  const addFromVar = node.querySelector('.mv-add-from-var');
  const next = node.querySelector('.mv-next');
  const audio = node.querySelector('.mv-audio');
  const upBtn = node.querySelector('.move-up');
  const downBtn = node.querySelector('.move-down');
  const delBtn = node.querySelector('.move-del');

  typeSel.value = move.type || 'say';
  wrap.dataset.type = typeSel.value;
  text.value = move.text || '';
  branch.value = move.branch || '';
  options.value = (move.options || []).join(', ');
  setvar.value = move.set_variable || '';
  addinterest.value = move.add_interest || '';
  addFromAnswer.checked = !!move.add_interest_from_answer;
  addFromVar.checked = !!move.add_interest_from_variable;
  next.value = move.next ? JSON.stringify(move.next) : '';
  audio.value = move.audio || '';

  typeSel.onchange = () => { wrap.dataset.type = typeSel.value; };
  upBtn.onclick = () => moveRowReorder(wrap, -1);
  downBtn.onclick = () => moveRowReorder(wrap, +1);
  delBtn.onclick = () => wrap.remove();

  els.moves.appendChild(node);
}

function moveRowReorder(row, delta) {
  const parent = els.moves;
  const rows = Array.from(parent.querySelectorAll('.move-row'));
  const i = rows.indexOf(row);
  const j = i + delta;
  if (j < 0 || j >= rows.length) return;
  if (delta < 0) parent.insertBefore(row, rows[j]);
  else parent.insertBefore(rows[j], row);
}

function collectForm() {
  const type = els.dlg_type.value || 'functional';
  const d = {
    id: els.dlg_id.value.trim(),
    type,
    functional_type: type === 'functional' ? (els.dlg_functional_type.value.trim() || undefined) : undefined,
    thread: type === 'narrative' ? (els.dlg_thread.value.trim() || undefined) : undefined,
    position: type === 'narrative' ? Number(els.dlg_position.value) : undefined,
    theme: type === 'chitchat' ? (els.dlg_theme.value.trim() || undefined) : undefined,
    topics: type === 'chitchat' ? splitComma(els.dlg_topics.value) : undefined,
    dependencies: splitComma(els.dlg_deps.value),
    variable_dependencies: splitComma(els.dlg_vdeps.value),
    moves: collectMoves(),
  };
  // prune undefined/empty arrays
  for (const k of Object.keys(d)) {
    if (d[k] === undefined) delete d[k];
    if (Array.isArray(d[k]) && d[k].length === 0) delete d[k];
  }
  return d;
}

function collectMoves() {
  const rows = Array.from(els.moves.querySelectorAll('.move-row'));
  return rows.map(row => {
    const get = sel => row.querySelector(sel);
    const type = get('.mv-type').value;
    const mv = { type };
    const text = get('.mv-text').value.trim();
    if (text) mv.text = text;
    const branch = get('.mv-branch').value.trim();
    if (branch) mv.branch = branch;
    const options = splitComma(get('.mv-options').value);
    if (options.length) mv.options = options;
    const setv = get('.mv-setvar').value.trim();
    if (setv) mv.set_variable = setv;
    const addi = get('.mv-addinterest').value.trim();
    if (addi) mv.add_interest = addi;
    if (get('.mv-add-from-answer').checked) mv.add_interest_from_answer = true;
    if (get('.mv-add-from-var').checked) mv.add_interest_from_variable = true;
    const nextRaw = get('.mv-next').value.trim();
    if (nextRaw) {
      try { mv.next = JSON.parse(nextRaw); } catch (e) { alert('Invalid JSON in move.next'); throw e; }
    }
    const audio = get('.mv-audio').value.trim();
    if (audio) mv.audio = audio;
    return mv;
  });
}

function splitComma(v) {
  return v.split(',').map(s => s.trim()).filter(Boolean);
}

function onApply() {
  if (state.selectedIndex < 0) return;
  const updated = collectForm();
  // require id + type
  if (!updated.id) return alert('Dialog id is required');
  if (!updated.type) return alert('Dialog type is required');

  state.dialogs[state.selectedIndex] = updated;
  renderList();
}

function newDialogOfType(type) {
  const id = `dlg_${Date.now()}`;
  let base = { id, type, moves: [] };
  if (type === 'functional') {
    base.functional_type = 'generic';
  } else if (type === 'narrative') {
    base.thread = '';
    base.position = 1;
  } else if (type === 'chitchat') {
    base.theme = '';
    base.topics = [];
  }
  state.dialogs.push(base);
  state.selectedIndex = state.dialogs.length - 1;
  renderList();
  selectIndex(state.selectedIndex);
  applyTypeTemplate(type);
}

function deleteDialog() {
  if (state.selectedIndex < 0) return;
  const d = state.dialogs[state.selectedIndex];
  if (!confirm(`Delete dialog ${d.id}?`)) return;
  state.dialogs.splice(state.selectedIndex, 1);
  state.selectedIndex = -1;
  renderList();
  selectIndex(-1);
}

function saveJSON() {
  const data = JSON.stringify(state.dialogs, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'dialogs.json';
  a.click();
  URL.revokeObjectURL(url);
}

function loadFromFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const json = JSON.parse(reader.result);
      if (!Array.isArray(json)) throw new Error('Expected an array of dialogs');
      state.dialogs = json;
      state.selectedIndex = -1;
      renderList();
      selectIndex(-1);
    } catch (e) {
      alert('Invalid dialogs.json: ' + e.message);
    }
  };
  reader.readAsText(file);
}

// wire events
els.fileInput.addEventListener('change', (e) => {
  const file = e.target.files && e.target.files[0];
  if (file) loadFromFile(file);
});
els.saveBtn.addEventListener('click', saveJSON);
els.newFunctionalBtn?.addEventListener('click', () => newDialogOfType('functional'));
els.newNarrativeBtn?.addEventListener('click', () => newDialogOfType('narrative'));
els.newChitchatBtn?.addEventListener('click', () => newDialogOfType('chitchat'));
els.deleteDialogBtn.addEventListener('click', deleteDialog);
els.searchBox.addEventListener('input', renderList);
els.addMoveBtn.addEventListener('click', () => addMoveRow());
els.applyBtn.addEventListener('click', onApply);
els.dlg_type.addEventListener('change', () => {
  els.editor.dataset.type = els.dlg_type.value;
  updateTypeVisibility();
});

// initial render
renderList();
selectIndex(-1);

// For new dialogs: set type visibility and clear irrelevant inputs so authors only see what matters
function applyTypeTemplate(type) {
  els.dlg_type.value = type;
  els.editor.dataset.type = type;
  if (type === 'functional') {
    // Keep only functional_type visible; clear other fields
    els.dlg_thread.value = '';
    els.dlg_position.value = '';
    els.dlg_theme.value = '';
    els.dlg_topics.value = '';
  } else if (type === 'narrative') {
    els.dlg_functional_type.value = '';
    els.dlg_theme.value = '';
    els.dlg_topics.value = '';
  } else if (type === 'chitchat') {
    els.dlg_functional_type.value = '';
    els.dlg_thread.value = '';
    els.dlg_position.value = '';
  }
  updateTypeVisibility();
}

// Ensure only relevant sections are visible for the current type (robust beyond CSS)
function updateTypeVisibility() {
  const t = els.dlg_type.value;
  const all = document.querySelectorAll('.type-functional, .type-narrative, .type-chitchat');
  // Hide all type-specific fields with inline style to override CSS
  all.forEach(n => { n.style.display = 'none'; });
  // Show only the ones for current type
  if (t === 'functional') {
    document.querySelectorAll('.type-functional').forEach(n => { n.style.display = ''; });
  } else if (t === 'narrative') {
    document.querySelectorAll('.type-narrative').forEach(n => { n.style.display = ''; });
  } else if (t === 'chitchat') {
    document.querySelectorAll('.type-chitchat').forEach(n => { n.style.display = ''; });
  }
}

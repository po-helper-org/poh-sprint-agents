  // Общий движок двух отчётов из одних данных: отчёт PO (sprint-report.html, навык
  // actual-sprint) и бизнес-отчёт «ФАКТ | спринт» (sprint-business.html, навык
  // sprint-business). Здесь данные команд, статусы, корзина заметок, сайдбары и
  // графики; своё у каждой страницы — в её шаблоне.
  // -------------------------------------------------------------------
  // TEAMS: по одному объекту на команду — то, что отдаёт сборщик команды
  // (contract/team.schema.json). Каждый — { slug, team, boardName, boardUrl,
  //            jiraBase, sprintName, epics, metrics, burndown, control,
  //            velocity, logs, statusMap?, notes?, _meta }.
  // Одна страница обслуживает все команды: переключатель в шапке.
  var TEAMS = {{TEAMS_JSON}};

  var team = TEAMS[0];
  var REPORT_ID, JIRA_BASE, EPICS, METRICS, BURNDOWN, CONTROL, VELOCITY, LOGS, STATUS_MAP;

  function useTeam(slug) {
    team = TEAMS.find(function (t) { return t.slug === slug; }) || TEAMS[0];
    // REPORT_ID разводит localStorage-заметки: у каждой команды свои
    REPORT_ID = team.slug;
    // раскладку статусов считает сборщик команды и кладёт в statusMap: у команд
    // разные workflow. Нет карты (старый файл данных) — падаем в classifyBucket.
    STATUS_MAP = team.statusMap || null;
    JIRA_BASE = team.jiraBase;
    EPICS = team.epics; METRICS = team.metrics; BURNDOWN = team.burndown;
    CONTROL = team.control; VELOCITY = team.velocity; LOGS = team.logs;
  }
  // -------------------------------------------------------------------

  // Бакеты статусов. Порядок = порядок вывода счётчиков в строке эпика.
  // phrase — формулировка для подсказки при наведении («2 — в бэклоге»).
  var BUCKETS = [
    { id: 'open',     label: 'Открыто',       cls: 'b-open',     phrase: 'в бэклоге' },
    { id: 'blocked',  label: 'Заблокировано', cls: 'b-blocked',  phrase: 'заблокировано' },
    { id: 'progress', label: 'В работе',      cls: 'b-progress', phrase: 'в работе' },
    { id: 'testing',  label: 'Тестирование',  cls: 'b-testing',  phrase: 'в тестировании' },
    { id: 'review',   label: 'Ревью',         cls: 'b-review',   phrase: 'в ревью' },
    { id: 'done',     label: 'Готово',        cls: 'b-done',     phrase: 'готово' }
  ];

  // Маппинг реального статуса JIRA -> бакет (см. resources/status_mapping.md).
  // Порядок проверок важен и выверен регрессией по всем ~330 статусам инстанса.
  var DONE_EXACT = [
    'закрыт', 'закрыта', 'закрыто', 'готово', 'сделано', 'выполнено', 'выполнена',
    'завершено', 'завершена', 'отменен', 'отменён', 'отменена', 'отменено',
    'отклонен', 'отклонён', 'отклонена', 'отклонено', 'решён', 'решен', 'решена'
  ];

  function classifyBucket(status, category) {
    if (STATUS_MAP) {
      var mapped = STATUS_MAP[status];
      if (mapped) return mapped;
    }
    var s = (status || '').trim().toLowerCase();

    // 1. Категория JIRA "Выполнено" — авторитетный и единственный широкий признак готовности.
    //    Подстрочный поиск по имени здесь недопустим: "Аналитика завершена", "Готово к закрытию",
    //    "Ожидает решения КЦ" содержат done-подобные корни, но финальными НЕ являются.
    if (category === 'Выполнено') return 'done';
    if (DONE_EXACT.indexOf(s) !== -1) return 'done';

    // 2. Блокировки и ожидания — раньше остальных: "Ожидает тестирование" это очередь, не тесты.
    if (/блок|ожида|пауза|на паузе|hold|wait|отложен|приостановл/.test(s)) return 'blocked';

    // 3. Тестирование раньше ревью: "Готово к тестированию" — про тесты.
    if (/тест|qa/.test(s)) return 'testing';

    // 4. Ревью / приёмка / согласование.
    if (/ревью|review|проверк|приемк|приёмк|согласован|утвержд/.test(s)) return 'review';

    // 5. Дефолт по категории JIRA.
    if (category === 'К выполнению') return 'open';
    return 'progress';
  }

  function bucketClass(status, category) {
    var id = classifyBucket(status, category);
    for (var i = 0; i < BUCKETS.length; i++) {
      if (BUCKETS[i].id === id) return BUCKETS[i].cls;
    }
    return 'b-open';
  }

  // Агрегация по ВСЕЙ иерархии эпика: каждая история + каждая её подзадача = 1 единица.
  function tallyEpic(epic) {
    var counts = {};
    BUCKETS.forEach(function (b) { counts[b.id] = 0; });

    (epic.stories || []).forEach(function (story) {
      counts[classifyBucket(story.status, story.category)]++;
      (story.subtasks || []).forEach(function (sub) {
        counts[classifyBucket(sub.status, sub.category)]++;
      });
    });

    counts.total = BUCKETS.reduce(function (acc, b) { return acc + counts[b.id]; }, 0);
    return counts;
  }

  function jiraUrl(key) { return JIRA_BASE + '/browse/' + key; }

  // Сколько дней статус не менялся. Считается в браузере от текущей даты,
  // поэтому страница не «протухает»: в данных лежит ISO-дата последней смены статуса.
  // Больше STALE_DAYS дней без движения — подсвечиваем красным.
  var STALE_DAYS = 3;

  function statusAge(iso) {
    if (!iso) return null;
    var then = new Date(iso);
    if (isNaN(then.getTime())) return null;
    var days = Math.floor((Date.now() - then.getTime()) / 86400000);
    if (days < 0) days = 0;
    return days;
  }

  // Готовые задачи по определению стоят без движения — красить их «просрочкой» смысла нет,
  // поэтому для бакета done возраст всегда зелёный и никогда не stale.
  function ageHtml(iso, status, category) {
    var isDone = classifyBucket(status, category) === 'done';
    var days = statusAge(iso);
    if (days === null) {
      return '<span class="age' + (isDone ? ' done' : '') + '" title="Дата смены статуса неизвестна">—</span>';
    }
    var label = days + 'д';
    var title = isDone
      ? 'Закрыто ' + (days === 0 ? 'сегодня' : days + ' дн. назад')
      : (days === 0 ? 'Статус изменён сегодня' : 'Статус не менялся ' + days + ' дн.');
    var cls = isDone ? ' done' : (days > STALE_DAYS ? ' stale' : '');
    return '<span class="age' + cls + '" title="' + esc(title) + '">' + label + '</span>';
  }

  // Инициалы исполнителя: "Фамилия Имя Отчество" -> "ФИ" (фамилия + имя).
  // Полное имя показывается подсказкой при наведении.
  function whoHtml(name) {
    if (!name) {
      return '<span class="who none">—<span class="who-tip">Исполнитель не назначен</span></span>';
    }
    var parts = String(name).trim().split(/\s+/);
    var initials = parts.slice(0, 2).map(function (p) { return p.charAt(0).toUpperCase(); }).join('');
    // В подсказке переставляем «Фамилия Имя Отчество» в «Имя Фамилия».
    // Но если вторая часть — одна буква (инициал или метка вида «Участник А»),
    // переставлять нечего: получится «А Участник».
    var full = (parts.length >= 2 && parts[1].replace('.', '').length > 1)
      ? parts[1] + ' ' + parts[0]
      : name;
    return '<span class="who" title="' + esc(name) + '">' + esc(initials) +
      '<span class="who-tip">' + esc(full) + '</span></span>';
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : s;
    return d.innerHTML;
  }

  var overlay = document.getElementById('overlay');
  var panelStack = document.getElementById('panelStack');
  var stackKey = document.getElementById('stackKey');
  var stackTitle = document.getElementById('stackTitle');
  var storiesLabel = document.getElementById('storiesLabel');
  var storiesBody = document.getElementById('storiesBody');

  // ------------------------- заметки (корзина) -------------------------
  // Как на странице ревью БФТ: заметки копятся в корзине справа вверху, каждую
  // можно поправить или удалить, наружу они уходят готовым промтом для ИИ.
  // У заметки необязательная привязка к сущности (эпик, история, подзадача или
  // любой ключ вне отчёта) — чтобы LLM сразу понимала, о чём речь.
  // Хранение — localStorage браузера, своя корзина у каждой команды и спринта.
  function commentsKey() { return 'actual-sprint:' + REPORT_ID + ':comments:' + team.sprintName; }

  function loadComments() {
    try {
      var list = JSON.parse(localStorage.getItem(commentsKey()) || '[]');
      return Array.isArray(list) ? list : [];
    } catch (e) { return []; }
  }

  function saveComments(list) {
    try { localStorage.setItem(commentsKey(), JSON.stringify(list)); } catch (e) {}
  }

  function newId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  function addComment(target, text) {
    text = String(text || '').trim();
    if (!text) return false;
    var list = loadComments();
    list.push({ id: newId(), at: new Date().toISOString(), target: target, text: text });
    saveComments(list);
    refreshComments();
    return true;
  }

  function updateComment(id, text, target) {
    text = String(text || '').trim();
    if (!text) return false;
    saveComments(loadComments().map(function (c) {
      return c.id === id ? Object.assign({}, c, { text: text, target: target, editedAt: new Date().toISOString() }) : c;
    }));
    refreshComments();
    return true;
  }

  function removeComment(id) {
    saveComments(loadComments().filter(function (c) { return c.id !== id; }));
    refreshComments();
  }

  // Заметки прошлых версий страницы (textarea в панели и файл sprint-report-notes.json)
  // один раз переезжают в корзину, чтобы ничего не потерялось. Старые ключи не трогаем.
  function migrateNotes() {
    var flag = 'actual-sprint:' + REPORT_ID + ':notes-migrated';
    if (localStorage.getItem(flag)) return;
    var prefix = 'actual-sprint:' + REPORT_ID + ':note:';
    var bag = {};
    Object.keys(team.notes || {}).forEach(function (k) { bag[k] = team.notes[k]; });
    Object.keys(localStorage).forEach(function (k) {
      if (k.indexOf(prefix) === 0 && localStorage.getItem(k)) bag[k.slice(prefix.length)] = localStorage.getItem(k);
    });
    var list = loadComments();
    Object.keys(bag).forEach(function (rowId) {
      var text = String(bag[rowId] || '').trim();
      if (!text) return;
      var epic = EPICS.find(function (e) { return e.rowId === rowId; });
      var target = epic ? epicTarget(epic)
        : { kind: 'general', title: rowId === '__metrics__' ? 'Сводный отчёт' : rowId === '__logs__' ? 'Лента изменений' : '' };
      list.push({ id: 'm-' + rowId, at: new Date().toISOString(), target: target, text: text, migrated: true });
    });
    saveComments(list);
    localStorage.setItem(flag, '1');
  }

  // --- к чему заметка: снимок сущности на момент записи, чтобы промт читался
  //     и тогда, когда данные отчёта уже пересобраны
  function epicTarget(epic) {
    return { kind: 'epic', key: epic.epicKey, title: epic.epicTitle || 'Без эпика',
             rowId: epic.rowId, priority: epic.epicPriority || null };
  }

  function itemTarget(kind, item, epic) {
    return { kind: kind, key: item.key, title: item.title || item.summary, status: item.status,
             priority: item.priority || null, assignee: item.assignee || null,
             epicKey: epic.epicKey, epicTitle: epic.epicTitle, rowId: epic.rowId };
  }

  var GENERAL = { kind: 'general' };
  var KIND_NAME = { epic: 'Эпик', story: 'История', subtask: 'Подзадача', event: 'Задача',
                    ref: 'Вне отчёта', chart: 'График', insight: 'Инсайд ИИ', slide: 'Слайд презентации' };

  // все сущности текущей команды по ключу: для привязки из корзины и подсказок
  function entityIndex() {
    var idx = {};
    EPICS.forEach(function (e) {
      if (e.epicKey) idx[e.epicKey.toUpperCase()] = epicTarget(e);
      (e.stories || []).forEach(function (st) {
        idx[st.key.toUpperCase()] = itemTarget('story', st, e);
        (st.subtasks || []).forEach(function (sub) { idx[sub.key.toUpperCase()] = itemTarget('subtask', sub, e); });
      });
    });
    return idx;
  }

  function fillRefList() {
    var idx = entityIndex();
    document.getElementById('refList').innerHTML = Object.keys(idx).map(function (k) {
      var t = idx[k];
      return '<option value="' + esc(t.key) + '">' + esc(KIND_NAME[t.kind] + ' · ' + t.title) + '</option>';
    }).join('');
  }

  // «INIT-132» или «INIT-132 — что угодно» → снимок сущности; ключ не из отчёта
  // (история вне спринта) тоже годится; пусто → заметка без привязки
  function resolveRef(value) {
    value = String(value || '').trim();
    if (!value) return GENERAL;
    var m = value.match(/^[A-Za-zА-Яа-яЁё][\wЀ-ӿ]*-\d+/);
    var key = m ? m[0].toUpperCase() : null;
    var known = key ? entityIndex()[key] : null;
    if (known) return known;
    return { kind: 'ref', key: key || value, title: key ? value.slice(m[0].length).replace(/^[\s—–-]+/, '') : '' };
  }

  function refValue(t) { return t && t.kind !== 'general' && t.key ? t.key : ''; }

  // одна строка «к чему»: и для корзины, и для промта
  function targetLine(t) {
    if (!t || t.kind === 'general') return 'без привязки' + (t && t.title ? ' · ' + t.title : '');
    var head = KIND_NAME[t.kind] + (t.key ? ' ' + t.key : '') + (t.title ? ' «' + t.title + '»' : '');
    var parts = [head];
    if ((t.kind === 'story' || t.kind === 'subtask') && t.epicTitle) {
      parts.push('эпик ' + (t.epicKey ? t.epicKey + ' ' : '') + '«' + t.epicTitle + '»');
    }
    if (t.priority) parts.push('приоритет ' + t.priority);
    if (t.status) parts.push('статус ' + t.status);
    if (t.assignee) parts.push('исполнитель ' + t.assignee);
    return parts.join(' · ');
  }

  function stamp(iso, withYear) {
    var d = new Date(iso);
    var two = function (n) { return ('0' + n).slice(-2); };
    return two(d.getDate()) + '.' + two(d.getMonth() + 1) + (withYear ? '.' + d.getFullYear() : '') +
      ' ' + two(d.getHours()) + ':' + two(d.getMinutes());
  }

  // Промт для ИИ: контекст отчёта, формат строки и заметки по порядку.
  // В квадратных скобках — к чему заметка; по ним LLM сразу находит сущность.
  function buildPrompt(list) {
    if (!list.length) return '';
    var when = team._meta && team._meta.collectedAt ? ' · данные JIRA на ' + stamp(team._meta.collectedAt, true) : '';
    var out = ['Заметки PO к отчёту спринта — учти их при разборе спринта и в ответах.',
               'Команда «' + team.team + '» · ' + team.sprintName + ' · доска «' + team.boardName + '»' + when + '.',
               'Формат: номер. [к чему относится] текст заметки. [без привязки] — заметка о процессе в целом.', ''];
    list.forEach(function (c, i) {
      var lines = String(c.text).split('\n');
      out.push((i + 1) + '. [' + targetLine(c.target) + '] ' + lines[0]);
      lines.slice(1).forEach(function (line) { out.push('   ' + line); });
    });
    return out.join('\n');
  }

  function copyText(text) {
    // file:// и старые браузеры без Clipboard API — через скрытое поле
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      return ok ? Promise.resolve() : Promise.reject(new Error('copy'));
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(fallback);
    }
    return fallback();
  }

  // --- иконки: контур 1.4px в сетке 16×16, как в панели poh-okr-plugin
  var ICON = {
    pencil: 'M10.4 3.4l2.2 2.2-6.9 6.9-2.9.7.7-2.9zM9.2 4.6l2.2 2.2',
    trash: 'M3.4 4.6h9.2M6.4 4.6V3.4h3.2v1.2M5 4.6l.6 8.2h4.8l.6-8.2',
    eye: 'M1.8 8s2.3-4.2 6.2-4.2S14.2 8 14.2 8s-2.3 4.2-6.2 4.2S1.8 8 1.8 8zM8 6.3a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 0 0 0-3.4'
  };
  function svgIcon(name) {
    return '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"' +
      ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + ICON[name] + '"/></svg>';
  }
  function icoBtn(name, title, attr, cls) {
    return '<button class="ico' + (cls ? ' ' + cls : '') + '" type="button" ' + attr +
      ' title="' + title + '" aria-label="' + title + '">' + svgIcon(name) + '</button>';
  }

  // --- корзина
  var notesPanel = document.getElementById('notesPanel');
  var notesToggle = document.getElementById('notesToggle');
  var editingId = null;

  // подпись под заметкой: только если привязана — «INIT-132 · Сервис приёма событий»
  function refLineHtml(t) {
    if (!t || t.kind === 'general') return '';
    var text = (t.key ? t.key : KIND_NAME[t.kind]) + (t.title ? ' · ' + t.title : '');
    return '<span class="nref-line" title="' + esc(targetLine(t)) + '">' + esc(text) + '</span>';
  }

  function noteItemHtml(c) {
    if (c.id === editingId) {
      return '<div class="nrow editing" data-id="' + esc(c.id) + '">' +
        '<textarea class="nedit-text" title="Enter — сохранить, Esc — отмена">' + esc(c.text) + '</textarea>' +
        '<input class="nref nedit-ref" list="refList" autocomplete="off" value="' + esc(refValue(c.target)) + '"' +
        ' placeholder="К чему — ключ эпика или задачи, необязательно"></div>';
    }
    var tip = 'Добавлено ' + stamp(c.at, true) + (c.editedAt ? ', изменено ' + stamp(c.editedAt, true) : '') +
      (c.migrated ? ' · перенесено из заметки' : '');
    return '<div class="nrow" data-id="' + esc(c.id) + '" title="' + esc(tip) + '">' +
      '<div class="ntext">' + esc(c.text) + refLineHtml(c.target) + '</div>' +
      '<div class="nacts">' + icoBtn('pencil', 'Редактировать', 'data-edit') +
        icoBtn('trash', 'Удалить', 'data-del', 'danger') + '</div></div>';
  }

  function renderNotes() {
    var list = loadComments();
    document.getElementById('cCount').textContent = list.length;
    var box = document.getElementById('itemsList');
    box.innerHTML = list.map(noteItemHtml).join('');
    var empty = document.getElementById('nEmpty');
    if (!list.length && !empty) {
      box.insertAdjacentHTML('beforebegin', '<p class="nempty" id="nEmpty">Заметок пока нет. Правый клик по строке отчёта — заметка к ней.</p>');
    } else if (list.length && empty) {
      empty.remove();
    }
    var prompt = buildPrompt(list);
    document.getElementById('promptOut').value = prompt;
    document.getElementById('copyBtn').disabled = !prompt;

    box.querySelectorAll('.nrow').forEach(function (item) {
      var id = item.dataset.id;
      var q = function (sel) { return item.querySelector(sel); };
      if (q('[data-del]')) q('[data-del]').addEventListener('click', function () { removeComment(id); });
      if (q('[data-edit]')) q('[data-edit]').addEventListener('click', function () {
        editingId = id; renderNotes();
        var ta = box.querySelector('.nedit-text');
        ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      });
      if (item.classList.contains('editing')) {
        var save = function () {
          // ключ не трогали — оставляем снимок сущности как был, а не пересобираем его
          var old = loadComments().find(function (c) { return c.id === id; });
          var ref = q('.nedit-ref').value.trim();
          var target = old && ref === refValue(old.target) ? old.target : resolveRef(ref);
          if (updateComment(id, q('.nedit-text').value, target)) editingId = null;
          renderNotes();
        };
        var cancel = function () { editingId = null; renderNotes(); };
        [q('.nedit-text'), q('.nedit-ref')].forEach(function (el) {
          el.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); save(); }
            if (e.key === 'Escape') { e.stopPropagation(); cancel(); }
          });
        });
      }
    });
  }

  function setNotesOpen(open) {
    notesPanel.classList.toggle('open', open);
    notesToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) editingId = null;
  }

  // сколько заметок у задачи и у эпика со всей его иерархией
  function commentCounts() {
    var byKey = {}, byRow = {};
    loadComments().forEach(function (c) {
      var t = c.target || {};
      if (t.key) byKey[t.key] = (byKey[t.key] || 0) + 1;
      if (t.rowId) byRow[t.rowId] = (byRow[t.rowId] || 0) + 1;
    });
    return { byKey: byKey, byRow: byRow };
  }

  function cmarkHtml(n) { return n ? '<span class="cmark" title="Заметок: ' + n + '">' + n + '</span>' : ''; }

  function refreshComments() {
    renderNotes();
    var counts = commentCounts();
    pageMarks(counts);          // метки своей страницы: строки эпиков у отчёта PO, слайды у бизнес-отчёта
    document.querySelectorAll('[data-cmark]').forEach(function (el) {
      el.innerHTML = cmarkHtml(counts.byKey[el.dataset.cmark] || 0);
    });
  }

  // --- поле заметки по правому клику: сразу с привязкой к строке
  var cpop = document.getElementById('cpop');
  var cpopText = document.getElementById('cpopText');
  var cpopTarget = null;

  function renderPopExisting(target) {
    var box = document.getElementById('cpopExisting');
    var list = target.key ? loadComments().filter(function (c) { return c.target && c.target.key === target.key; }) : [];
    box.hidden = !list.length;
    box.innerHTML = list.map(function (c) {
      return '<div class="nrow"><div class="ntext">' + esc(c.text) + '</div>' +
        '<div class="nacts">' + icoBtn('trash', 'Удалить', 'data-pdel="' + esc(c.id) + '"', 'danger') + '</div></div>';
    }).join('');
    box.querySelectorAll('[data-pdel]').forEach(function (b) {
      b.addEventListener('click', function () { removeComment(b.dataset.pdel); renderPopExisting(target); });
    });
  }

  function openCommentPopup(target, x, y) {
    cpopTarget = target;
    document.getElementById('cpopTarget').innerHTML = refLineHtml(target) || '<span class="nref-line">Без привязки</span>';
    renderPopExisting(target);
    cpopText.value = '';
    cpop.hidden = false;
    var w = cpop.offsetWidth, h = cpop.offsetHeight;
    cpop.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
    cpop.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
    cpopText.focus({ preventScroll: true });
  }

  function closeCommentPopup() { cpop.hidden = true; cpopTarget = null; }

  function saveCommentPopup() {
    if (cpopTarget && addComment(cpopTarget, cpopText.value)) closeCommentPopup();
  }

  document.getElementById('cpopSave').addEventListener('click', saveCommentPopup);
  document.getElementById('cpopCancel').addEventListener('click', closeCommentPopup);
  // на сенсорном экране нет Enter/Esc в привычном смысле — подсказка про кнопки
  if (window.matchMedia && window.matchMedia('(hover: none)').matches) cpopText.placeholder = 'Заметка';
  cpopText.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); saveCommentPopup(); }
    if (e.key === 'Escape') { e.stopPropagation(); closeCommentPopup(); }
  });
  // клик мимо закрывает пустое поле; начатый текст не теряем
  document.addEventListener('mousedown', function (e) {
    if (!cpop.hidden && !cpop.contains(e.target) && !cpopText.value.trim()) closeCommentPopup();
  });

  // Правый клик по любой строке с data-ctx открывает поле заметки к ней.
  // Цель берётся из реестра, заполняемого при отрисовке строк.
  var ctxTargets = {}, ctxSeq = 0;
  function ctxId(target) {
    var id = 'c' + (ctxSeq++);
    ctxTargets[id] = target;
    return id;
  }
  function ctxAttr(target) { return ' data-ctx="' + ctxId(target) + '"'; }
  // Подсказка «i» открывается туда, где есть место: у нижних графиков — вверх,
  // и не выше видимой области, иначе низ подсказки уходит за край панели.
  function placeInfo(e) {
    var icon = e.target.closest && e.target.closest('.info');
    if (!icon) return;
    var tip = icon.querySelector('.info-tip');
    if (window.matchMedia('(max-width: 640px)').matches) { icon.classList.remove('up'); tip.style.maxHeight = ''; return; }
    var r = icon.getBoundingClientRect(), gap = 16;
    var below = window.innerHeight - r.bottom - gap, above = r.top - gap;
    var up = below < Math.min(tip.scrollHeight, 360) && above > below;
    icon.classList.toggle('up', up);
    tip.style.maxHeight = Math.max(160, (up ? above : below) - 8) + 'px';
  }
  document.addEventListener('mouseover', placeInfo);
  document.addEventListener('focusin', placeInfo);

  document.addEventListener('contextmenu', function (e) {
    var el = e.target.closest && e.target.closest('[data-ctx]');
    if (!el || !ctxTargets[el.dataset.ctx]) return;
    e.preventDefault();
    openCommentPopup(ctxTargets[el.dataset.ctx], e.clientX, e.clientY);
  });

  // Телефон: правой кнопки нет, а Safari на iOS не шлёт contextmenu по долгому
  // нажатию. Держим палец 0,5 с на строке — то же поле заметки. Сдвиг пальца
  // (прокрутка) отменяет; клик, который iOS пришлёт после отпускания, гасим —
  // иначе вслед за заметкой открылась бы панель эпика или ссылка в JIRA.
  var LONG_PRESS_MS = 500;
  var press = null, swallowNextRelease = false, swallowClickUntil = 0;
  function cancelPress() {
    if (!press) return;
    clearTimeout(press.timer);
    press.el.classList.remove('pressing');
    press = null;
  }
  document.addEventListener('touchstart', function (e) {
    cancelPress();
    swallowClickUntil = 0;   // новое касание — новый жест: хвост прошлого уже пришёл
    if (e.touches.length !== 1) return;
    var el = e.target.closest && e.target.closest('[data-ctx]');
    if (!el || !ctxTargets[el.dataset.ctx]) return;
    var t = e.touches[0];
    press = { el: el, x: t.clientX, y: t.clientY };
    el.classList.add('pressing');
    press.timer = setTimeout(function () {
      var target = ctxTargets[el.dataset.ctx];
      var at = press;
      cancelPress();
      swallowNextRelease = true;
      openCommentPopup(target, at.x, at.y);
    }, LONG_PRESS_MS);
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (!press) return;
    var t = e.touches[0];
    if (Math.abs(t.clientX - press.x) > 10 || Math.abs(t.clientY - press.y) > 10) cancelPress();
  }, { passive: true });
  // после долгого нажатия отпускание пальца не должно стать тапом: без этого
  // синтетические mousedown и click закрыли бы поле и открыли строку под ним
  document.addEventListener('touchend', function (e) {
    cancelPress();
    if (!swallowNextRelease) return;
    swallowNextRelease = false;
    e.preventDefault();
    swallowClickUntil = Date.now() + 400;   // если браузер всё же пришлёт мышиные события
  }, { passive: false });
  document.addEventListener('touchcancel', cancelPress);
  ['mousedown', 'click'].forEach(function (type) {
    document.addEventListener(type, function (e) {
      if (Date.now() < swallowClickUntil && !cpop.contains(e.target)) {
        e.preventDefault();
        e.stopPropagation();
        if (type === 'click') swallowClickUntil = 0;
      }
    }, true);
  });

  // «i» по тапу: наведения на сенсорном экране нет. Повторный тап или тап мимо закрывает.
  document.addEventListener('click', function (e) {
    var icon = e.target.closest && e.target.closest('.info');
    document.querySelectorAll('.info.open').forEach(function (other) {
      if (other !== icon) other.classList.remove('open');
    });
    if (icon && !e.target.closest('.info-tip')) icon.classList.toggle('open');
  });

  // --- приоритет: уровень выводим из имени, как бакет из статуса
  var PRIO_LEVELS = [
    { cls: 'p-highest', glyph: '⇈', rx: /блокир|критич|highest|blocker|critical|наивысш|срочн/ },
    { cls: 'p-lowest',  glyph: '⇊', rx: /lowest|trivial|незначит|минимальн/ },
    { cls: 'p-high',    glyph: '↑', rx: /высок|high|major|важн/ },
    { cls: 'p-low',     glyph: '↓', rx: /низк|low|minor/ },
    { cls: 'p-medium',  glyph: '=', rx: /средн|medium|normal|обычн|нормальн/ }
  ];

  function prioHtml(name) {
    if (!name) return '<span class="prio p-none" title="Приоритет не задан">·</span>';
    var s = String(name).toLowerCase();
    var lvl = PRIO_LEVELS.find(function (l) { return l.rx.test(s); }) || { cls: 'p-medium', glyph: '•' };
    return '<span class="prio ' + lvl.cls + '" title="Приоритет: ' + esc(name) + '">' + lvl.glyph + '</span>';
  }

  // общая шапка панели — заполняется один раз на открытие, не дублируется по колонкам
  function setStackHead(epic) {
    stackTitle.parentNode.setAttribute('data-ctx', ctxId(epicTarget(epic)));
    stackTitle.textContent = epic.epicTitle || 'Без эпика';
    if (!epic.epicKey) { stackKey.textContent = 'Без эпика'; return; }
    stackKey.innerHTML = '<a class="key-link" id="stackKeyLink" href="' + jiraUrl(epic.epicKey) +
      '" target="_blank" rel="noopener" title="Открыть в JIRA">' + esc(epic.epicKey) +
      '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"' +
      ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3"/></svg></a>';
  }

  // Строка задачи с разворотом подзадач — одна на панель спринта и на «Весь эпик».
  // tail — что показать справа от бейджа: возраст статуса или метку спринта.
  function storyNode(story, epic, counts, tail) {
    var wrap = document.createElement('div');
    wrap.className = 'story-item';
    var hasSubtasks = story.subtasks && story.subtasks.length > 0;

    var row = document.createElement('div');
    row.className = 'story-row';
    row.innerHTML =
      '<div class="story-title-wrap"' + ctxAttr(itemTarget('story', story, epic)) + '>' +
        '<button class="story-toggle" ' + (hasSubtasks ? '' : 'disabled') + '>▶</button>' +
        prioHtml(story.priority) +
        whoHtml(story.assignee) +
        '<a href="' + jiraUrl(story.key) + '" target="_blank" rel="noopener">' + esc(story.key) + ' — ' + esc(story.title) + '</a>' +
      '</div>' +
      '<div class="meta-wrap">' +
        '<span data-cmark="' + esc(story.key) + '">' + cmarkHtml(counts[story.key] || 0) + '</span>' +
        '<span class="status ' + bucketClass(story.status, story.category) + '">' + esc(story.status) + '</span>' +
        tail(story) +
      '</div>';
    wrap.appendChild(row);

    var subList = document.createElement('div');
    subList.className = 'sub-list';
    (story.subtasks || []).forEach(function (sub) {
      var subRow = document.createElement('div');
      subRow.className = 'sub-item';
      subRow.innerHTML = '<span class="story-title-wrap"' + ctxAttr(itemTarget('subtask', sub, epic)) + '>' +
        prioHtml(sub.priority) +
        whoHtml(sub.assignee) +
        '<a href="' + jiraUrl(sub.key) + '" target="_blank" rel="noopener">' + esc(sub.key) + ' — ' + esc(sub.summary) + '</a>' +
        '</span>' +
        '<div class="meta-wrap">' +
          '<span data-cmark="' + esc(sub.key) + '">' + cmarkHtml(counts[sub.key] || 0) + '</span>' +
          '<span class="status ' + bucketClass(sub.status, sub.category) + '">' + esc(sub.status) + '</span>' +
          (sub.statusChanged !== undefined ? ageHtml(sub.statusChanged, sub.status, sub.category) : '') +
        '</div>';
      subList.appendChild(subRow);
    });
    wrap.appendChild(subList);

    var toggleBtn = row.querySelector('.story-toggle');
    if (hasSubtasks) {
      toggleBtn.title = 'Подзадачи: ' + story.subtasks.length;
      toggleBtn.addEventListener('click', function () {
        toggleBtn.classList.toggle('open');
        subList.classList.toggle('open');
      });
    }
    return wrap;
  }

  function fillStoriesPanel(epic) {
    storiesBody.innerHTML = '';
    var counts = commentCounts().byKey;

    if (!epic.stories || !epic.stories.length) {
      var empty = document.createElement('div');
      empty.className = 'sidebar-empty';
      empty.textContent = 'Историй нет.';
      storiesBody.appendChild(empty);
      return;
    }
    epic.stories.forEach(function (story) {
      storiesBody.appendChild(storyNode(story, epic, counts, function (st) {
        return ageHtml(st.statusChanged, st.status, st.category);
      }));
    });
  }

  // ------------------------- весь эпик -------------------------
  // Полный объём эпика, не только спринт: когда будет выполнен и на чём прогноз, что
  // сделано и что осталось и в каком процессе. Один и тот же вид в отчёте PO («Смотреть
  // весь эпик») и в бизнес-отчёте (клик по KR).
  var SCOPE_ORDER = ['blocked', 'progress', 'testing', 'review', 'open'];
  var BUCKET_COLOR = { open: 'var(--c-open)', blocked: 'var(--c-blocked)', progress: 'var(--c-progress)',
                       testing: 'var(--c-testing)', review: 'var(--c-review)', done: 'var(--c-done)' };
  var scopeBtn = document.getElementById('scopeBtn');
  var scopeEpic = null, scopeOn = false;

  function sprintChip(item) {
    if (item.inSprint) return '<span class="chip-sprint now" title="В текущем спринте">в спринте</span>';
    if (item.sprint) return '<span class="chip-sprint" title="Была в спринте отчёта">' + esc(item.sprint) + '</span>';
    return '<span class="chip-sprint" title="Вне спринтов отчёта: бэклог или давнее">вне спринта</span>';
  }

  function scopeSection(id, title, n, body, closed) {
    var sec = document.createElement('section');
    sec.className = 'scope-sec' + (closed ? ' closed' : '');
    sec.dataset.sec = id;
    sec.innerHTML = '<button class="sec-head" type="button" aria-expanded="' + !closed + '">' + esc(title) +
      ' <span class="n">· ' + n + '</span><span class="arr">▼</span></button><div class="sec-body"></div>';
    var head = sec.querySelector('.sec-head');
    head.addEventListener('click', function () {
      sec.classList.toggle('closed');
      head.setAttribute('aria-expanded', String(!sec.classList.contains('closed')));
    });
    body.forEach(function (node) { sec.querySelector('.sec-body').appendChild(node); });
    return sec;
  }

  // ---------- сгорание эпика: объём, осталось, план и прогноз ----------
  // Как отчёт «сгорание эпика» в JIRA: сколько задач в эпике и сколько осталось по дням.
  // План — дедлайн эпика (duedate); прогноз — по темпу закрытия задач эпика в текущем
  // спринте (нет закрытий в спринте — за последние 4 недели).
  function isoDay(d) { return d.toISOString().slice(0, 10); }
  function ddmm(iso) { return iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) : '—'; }
  function dayMs(iso) { return new Date(iso + 'T12:00:00').getTime(); }
  function addDays(iso, n) { return isoDay(new Date(dayMs(iso) + n * 86400000)); }
  function ddmmyy(iso) { return iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(2, 4) : '—'; }

  function epicBurn(t, epic) {
    var items = (epic.scope || []).filter(function (it) { return it.created; });
    if (!items.length) return null;
    var today = ((t._meta && t._meta.collectedAt) || new Date().toISOString()).slice(0, 10);
    var isDone = function (it) { return classifyBucket(it.status, it.category) === 'done'; };
    var doneAt = function (it) { return isDone(it) ? (it.doneAt || today) : null; };
    var start = items.map(function (it) { return it.created; }).sort()[0];
    var total = items.length, done = items.filter(isDone).length, left = total - done;
    var sprintStart = (t.burndown && t.burndown.start) || addDays(today, -14);
    var inSprint = items.filter(function (it) { var d = doneAt(it); return d && d >= sprintStart; }).length;
    var days = Math.max(1, (dayMs(today) - dayMs(sprintStart)) / 86400000);
    var basis = 'по темпу текущего спринта';
    var pace = inSprint / days;
    if (!pace) {
      var from = addDays(today, -28);
      pace = items.filter(function (it) { var d = doneAt(it); return d && d >= from; }).length / 28;
      basis = 'по темпу за 4 недели';
    }
    var forecast = left === 0 ? today : pace ? addDays(today, Math.ceil(left / pace)) : null;
    return { start: start, today: today, total: total, done: done, left: left, due: epic.epicDue || null,
             forecast: forecast, pace: pace, basis: basis, items: items, doneAt: doneAt };
  }

  function epicBurnChart(b) {
    var W = 640, H = 236, padL = 34, padR = 14, padT = 32, padB = 28;
    var horizon = addDays(b.today, 180);
    var endIso = [b.today, b.due, b.forecast && b.forecast <= horizon ? b.forecast : null].filter(Boolean).sort().pop();
    endIso = addDays(endIso, 7);
    var t0 = dayMs(b.start), t1 = dayMs(endIso);
    var xOf = function (iso) { return padL + (W - padL - padR) * (dayMs(iso) - t0) / (t1 - t0); };
    var yOf = function (v) { return padT + (H - padT - padB) * (1 - v / Math.max(1, b.total)); };
    var created = b.items.map(function (it) { return it.created; }).sort();
    var closed = b.items.map(b.doneAt).filter(Boolean).sort();
    var scope = [], left = [];
    for (var d = b.start; d <= b.today; d = addDays(d, 1)) {
      var n = created.filter(function (x) { return x <= d; }).length, c = closed.filter(function (x) { return x <= d; }).length;
      scope.push(xOf(d).toFixed(1) + ',' + yOf(n).toFixed(1));
      left.push(xOf(d).toFixed(1) + ',' + yOf(n - c).toFixed(1));
    }
    var parts = [];
    [0, Math.round(b.total / 2), b.total].forEach(function (v) {
      parts.push('<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + yOf(v).toFixed(1) + '" y2="' + yOf(v).toFixed(1) + '" stroke="#eee"/>');
      parts.push('<text x="4" y="' + (yOf(v) + 4).toFixed(1) + '" font-size="10" fill="#666">' + v + '</text>');
    });
    parts.push('<polyline points="' + scope.join(' ') + '" fill="none" stroke="#9ca3af" stroke-width="1.6"><title>Объём эпика, задач</title></polyline>');
    parts.push('<polygon points="' + xOf(b.start).toFixed(1) + ',' + yOf(0).toFixed(1) + ' ' + left.join(' ') + ' ' + xOf(b.today).toFixed(1) + ',' + yOf(0).toFixed(1) +
      '" fill="#2563eb" fill-opacity=".12" stroke="none"/>');
    parts.push('<polyline points="' + left.join(' ') + '" fill="none" stroke="#2563eb" stroke-width="2"><title>Осталось, задач</title></polyline>');
    if (b.forecast && b.left && b.forecast <= horizon) {
      parts.push('<line x1="' + xOf(b.today).toFixed(1) + '" y1="' + yOf(b.left).toFixed(1) + '" x2="' + xOf(b.forecast).toFixed(1) + '" y2="' + yOf(0).toFixed(1) +
        '" stroke="#2563eb" stroke-width="1.6" stroke-dasharray="5 4"/>');
    }
    var vline = function (iso, color, label, dash, dy) {
      var x = xOf(iso).toFixed(1);
      parts.push('<line x1="' + x + '" x2="' + x + '" y1="' + padT + '" y2="' + (H - padB) + '" stroke="' + color + '" stroke-width="1.4"' + (dash ? ' stroke-dasharray="4 3"' : '') + '/>');
      parts.push('<text x="' + x + '" y="' + (padT - 6 - (dy || 0)) + '" font-size="10.5" fill="' + color + '" text-anchor="middle">' + label + '</text>');
    };
    vline(b.today, '#111', 'сегодня', true, 0);
    if (b.due) vline(b.due, '#dc2626', 'план ' + ddmm(b.due), false, b.due === b.today ? 10 : 0);
    if (b.forecast && b.forecast <= horizon && b.forecast !== b.today) vline(b.forecast, '#2563eb', 'прогноз ' + ddmm(b.forecast), true, b.due && Math.abs(dayMs(b.due) - dayMs(b.forecast)) < 10 * 86400000 ? 11 : 0);
    parts.push('<text x="' + padL + '" y="' + (H - 8) + '" font-size="10" fill="#777">' + ddmm(b.start) + '</text>');
    parts.push('<text x="' + (W - padR) + '" y="' + (H - 8) + '" font-size="10" fill="#777" text-anchor="end">' + ddmm(endIso) + '</text>');
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' + parts.join('') + '</svg>';
  }

  function plDays(n) { var m10 = n % 10, m100 = n % 100; return n + ' ' + (m10 === 1 && m100 !== 11 ? 'день' : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? 'дня' : 'дней'); }
  function plTasks(n) { var m10 = n % 10, m100 = n % 100; return n + ' ' + (m10 === 1 && m100 !== 11 ? 'задача' : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? 'задачи' : 'задач'); }

  // Когда эпик будет выполнен, на чём держится прогноз — словами, а не только графиком.
  function epicBurnHtml(t, epic) {
    var b = epicBurn(t, epic);
    if (!b) return '<div class="eb"><div class="eb-title">Когда будет выполнен</div><div class="sidebar-empty">Нет дат задач эпика — прогноз не построить: нужен сборщик 1.4.0+.</div></div>';
    var late = b.due && b.forecast && b.forecast > b.due;
    var diff = b.due && b.forecast ? Math.round((dayMs(b.forecast) - dayMs(b.due)) / 86400000) : null;
    var verdict = !b.left ? '<span class="ok">эпик закрыт</span>'
      : !b.forecast ? '<span class="bad">темпа нет — прогноз не построить</span>'
      : b.due ? (late ? '<span class="bad">опоздание на ' + plDays(diff) + '</span>' : '<span class="ok">в срок' + (diff < 0 ? ', запас ' + plDays(-diff) : '') + '</span>') : '';
    var sprintStart = (t.burndown && t.burndown.start) || addDays(b.today, -14);
    var closedIn = function (from) { return b.items.filter(function (it) { var d = b.doneAt(it); return d && d >= from; }).length; };
    var spDays = Math.max(1, Math.round((dayMs(b.today) - dayMs(sprintStart)) / 86400000));
    var grew = b.items.filter(function (it) { return it.created >= addDays(b.today, -28); }).length;
    var why = [];
    if (!b.left) why.push('Все ' + plTasks(b.total) + ' эпика закрыты.');
    else if (b.basis === 'по темпу текущего спринта') {
      why.push('Темп: в текущем спринте (с ' + ddmm(sprintStart) + ', ' + plDays(spDays) + ') закрыто ' + plTasks(closedIn(sprintStart)) +
               ' эпика, ≈ ' + String(Math.round(b.pace * 70) / 10).replace('.', ',') + ' в неделю.');
    } else if (b.forecast) {
      why.push('В текущем спринте задач эпика не закрыто — темп взят за 4 недели: закрыто ' + plTasks(closedIn(addDays(b.today, -28))) +
               ', ≈ ' + String(Math.round(b.pace * 70) / 10).replace('.', ',') + ' в неделю.');
    } else why.push('Ни в текущем спринте, ни за 4 недели задачи эпика не закрывались — темпа для прогноза нет.');
    if (b.left && b.forecast) why.push('Осталось ' + plTasks(b.left) + ' → при том же темпе ещё ≈ ' + plDays(Math.round((dayMs(b.forecast) - dayMs(b.today)) / 86400000)) + ', до ' + ddmmyy(b.forecast) + '.');
    why.push(b.due ? 'План — срок эпика в JIRA: ' + ddmmyy(b.due) + '.' : 'Срок эпика в JIRA не задан — сравнить прогноз не с чем.');
    if (grew) why.push('Объём растёт: за 4 недели в эпик добавлено ' + plTasks(grew) + ' — новые задачи сдвинут прогноз.');
    why.push('Считается по числу задач, без оценки: крупные задачи в остатке делают прогноз оптимистичным.');
    return '<div class="eb"><div class="eb-title">Когда будет выполнен</div>' +
      '<div class="eb-kpis"><div><b>' + (b.left ? (b.forecast ? ddmmyy(b.forecast) : '—') : 'готов') + '</b><span>прогноз</span></div>' +
      '<div><b>' + (b.due ? ddmmyy(b.due) : '—') + '</b><span>плановая дата' + (b.due ? '' : ' не задана') + '</span></div>' +
      '<div><b>' + b.left + '<small>/' + b.total + '</small></b><span>осталось задач</span></div>' +
      (verdict ? '<div class="eb-verdict">' + verdict + '</div>' : '') + '</div>' + epicBurnChart(b) +
      '<div class="eb-legend"><span><i class="l-scope"></i>объём</span><span><i class="l-left"></i>осталось</span>' +
      '<span><i class="l-fc"></i>прогноз</span><span><i class="l-due"></i>план</span></div>' +
      '<div class="eb-why"><div class="eb-why-title">На чём прогноз</div><ul>' + why.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div></div>';
  }

  function renderScope(epic) {
    // у задач текущего спринта берём строку из данных спринта: там у подзадач есть
    // исполнитель и возраст статуса, которых поиск по эпику не отдаёт
    var sprintRows = {};
    (epic.stories || []).forEach(function (st) { sprintRows[st.key] = st; });
    var items = (epic.scope || []).map(function (it) {
      var st = it.inSprint && sprintRows[it.key];
      return st ? Object.assign({}, it, { subtasks: st.subtasks }) : it;
    });
    var counts = commentCounts().byKey;
    var byBucket = {};
    BUCKETS.forEach(function (b) { byBucket[b.id] = []; });
    items.forEach(function (it) { byBucket[classifyBucket(it.status, it.category)].push(it); });
    var done = byBucket.done, left = items.length - done.length;
    var pct = items.length ? Math.round(100 * done.length / items.length) : 0;
    var inSprint = items.filter(function (it) { return it.inSprint; }).length;

    storiesBody.innerHTML = '';
    var sum = document.createElement('div');
    sum.className = 'scope-sum';
    sum.innerHTML = '<span class="big">Сделано ' + done.length + ' из ' + items.length + ' · ' + pct + '%</span>' +
      '<span class="sub">задач эпика · ' + inSprint + ' в текущем спринте</span>' +
      '<div class="scope-bar" title="' + esc(BUCKETS.filter(function (b) { return byBucket[b.id].length; })
        .map(function (b) { return byBucket[b.id].length + ' — ' + b.phrase; }).join(', ')) + '">' +
      BUCKETS.filter(function (b) { return byBucket[b.id].length; }).map(function (b) {
        return '<i style="flex:' + byBucket[b.id].length + ';background:' + BUCKET_COLOR[b.id] + '"></i>';
      }).join('') + '</div>';
    storiesBody.appendChild(sum);
    // когда эпик будет выполнен и на чём прогноз — сразу под итогом
    storiesBody.insertAdjacentHTML('beforeend', epicBurnHtml(team, epic));

    if (!items.length) {
      storiesBody.insertAdjacentHTML('beforeend', '<div class="sidebar-empty">Задач в эпике нет.</div>');
      return;
    }

    // «Осталось» — по процессу: сначала то, что стоит, потом в работе, в конце не начатое
    var leftNodes = [];
    SCOPE_ORDER.forEach(function (id) {
      if (!byBucket[id].length) return;
      var b = BUCKETS.find(function (x) { return x.id === id; });
      var g = document.createElement('div');
      // по умолчанию свёрнуто: сначала картина по статусам, задачи — по клику
      g.className = 'scope-group closed';
      g.dataset.bucket = id;
      g.innerHTML = '<button class="grp-head" type="button" aria-expanded="false">' +
        '<span class="dot" style="background:' + BUCKET_COLOR[id] + '"></span>' +
        esc(b.label) + ' · ' + byBucket[id].length + '<span class="arr">▼</span></button>' +
        '<div class="grp-body"></div>';
      var head = g.querySelector('.grp-head'), body = g.querySelector('.grp-body');
      head.addEventListener('click', function () {
        g.classList.toggle('closed');
        head.setAttribute('aria-expanded', String(!g.classList.contains('closed')));
      });
      byBucket[id].forEach(function (it) { body.appendChild(storyNode(it, epic, counts, sprintChip)); });
      leftNodes.push(g);
    });
    // эпик может быть длинным: при открытии видны только итог и заголовки разделов
    storiesBody.appendChild(scopeSection('left', 'Что осталось', left, leftNodes, true));
    storiesBody.appendChild(scopeSection('done', 'Что выполнено', done.length,
      done.map(function (it) { return storyNode(it, epic, counts, sprintChip); }), true));
  }

  function setScopeMode(on) {
    scopeOn = on && !!(scopeEpic && scopeEpic.scope);
    scopeBtn.setAttribute('aria-pressed', String(scopeOn));
    scopeBtn.textContent = scopeOn ? '← Задачи спринта' : 'Смотреть весь эпик';
    storiesLabel.textContent = scopeOn ? 'Весь эпик' : 'Истории';
    if (scopeOn) renderScope(scopeEpic); else fillStoriesPanel(scopeEpic);
    storiesBody.parentNode.scrollTop = 0;
  }

  scopeBtn.addEventListener('click', function () { setScopeMode(!scopeOn); });

  // ------------------ Диаграмма управления ------------------
  function fmt(v) { return v === null || v === undefined ? '—' : String(v).replace('.', ','); }
  // X — дата закрытия, Y — Cycle Time задачи. Синяя линия — скользящее среднее,
  // светлая полоса — коридор ±σ, красная черта — порог выброса (среднее + σ).
  // Точки выше порога подсвечены и вынесены списком под графиком.
  // Цель заметки для задачи из диаграммы: из отчёта, если она там есть (с эпиком),
  // иначе — снимок того, что известно по строке диаграммы.
  function chartItemTarget(row, kind) {
    return entityIndex()[String(row.key).toUpperCase()] ||
      { kind: kind, key: row.key, title: row.title, status: row.status,
        assignee: row.assignee || null, rowId: null };
  }

  // Холст графиков: на странице — 560×210; операционный слайд презентации
  // рисует уже и выше, чтобы подписи осей оставались читаемыми в узкой ячейке.
  var CHART_BOX = null;
  function withChartBox(box, fn) {
    var prev = CHART_BOX;
    CHART_BOX = box;
    try { return fn(); } finally { CHART_BOX = prev; }
  }

  function controlChart(c, label, kind) {
    if (!c || !c.points || !c.points.length) {
      return '<div class="m-muted">Нет закрытых ' + esc(label) + ' за период.</div>';
    }

    var pts = c.points;
    var W = (CHART_BOX && CHART_BOX.W) || 560, H = (CHART_BOX && CHART_BOX.H) || 210, padL = 34, padR = 14, padT = 12, padB = 30;
    var innerW = W - padL - padR, innerH = H - padT - padB;
    var maxY = Math.max.apply(null, pts.map(function (p) { return p.cycle; })) || 1;

    var t0 = new Date(pts[0].doneAt).getTime();
    var t1 = new Date(pts[pts.length - 1].doneAt).getTime();
    var span = Math.max(t1 - t0, 1);
    var xOf = function (iso) { return padL + innerW * ((new Date(iso).getTime() - t0) / span); };
    var yOf = function (v) { return padT + innerH * (1 - v / maxY); };

    var parts = [];
    [0, Math.round(maxY / 2), Math.round(maxY)].forEach(function (v) {
      parts.push('<line x1="' + padL + '" y1="' + yOf(v).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + yOf(v).toFixed(1) + '" stroke="#eee"/>');
      parts.push('<text x="4" y="' + (yOf(v) + 4).toFixed(1) + '" font-size="10" fill="#666">' + v + '</text>');
    });

    // скользящее среднее по окну из 5 задач + коридор ±σ
    var WIN = 5, avg = [], band = [];
    pts.forEach(function (p, i) {
      var from = Math.max(0, i - Math.floor(WIN / 2));
      var win = pts.slice(from, from + WIN).map(function (q) { return q.cycle; });
      var m = win.reduce(function (a, v) { return a + v; }, 0) / win.length;
      var sd = Math.sqrt(win.reduce(function (a, v) { return a + (v - m) * (v - m); }, 0) / win.length);
      avg.push({ x: xOf(p.doneAt), y: yOf(m) });
      band.push({ x: xOf(p.doneAt), hi: yOf(Math.min(maxY, m + sd)), lo: yOf(Math.max(0, m - sd)) });
    });

    var bandPath = band.map(function (b, i) { return (i ? 'L' : 'M') + b.x.toFixed(1) + ' ' + b.hi.toFixed(1); }).join(' ') +
      ' ' + band.slice().reverse().map(function (b) { return 'L' + b.x.toFixed(1) + ' ' + b.lo.toFixed(1); }).join(' ') + ' Z';
    parts.push('<path d="' + bandPath + '" fill="#2563eb" fill-opacity="0.10"/>');
    parts.push('<path d="' + avg.map(function (a, i) { return (i ? 'L' : 'M') + a.x.toFixed(1) + ' ' + a.y.toFixed(1); }).join(' ') +
      '" fill="none" stroke="#2563eb" stroke-width="2"/>');

    // порог выброса
    parts.push('<line x1="' + padL + '" y1="' + yOf(c.limit).toFixed(1) + '" x2="' + (W - padR) +
      '" y2="' + yOf(c.limit).toFixed(1) + '" stroke="#dc2626" stroke-width="1.5"/>');

    // задачи в зоне риска: ещё не закрыты, но в работе дольше медианы.
    // Ставим их на «сегодня» — по вертикали столько, сколько уже длятся.
    var risks = (c.risks || []).filter(function (r) { return r.elapsed <= maxY; });
    var overflow = (c.risks || []).length - risks.length;
    if (c.risks && c.risks.length) {
      var xRisk = W - padR - 6;
      risks.forEach(function (r) {
        parts.push('<circle cx="' + xRisk.toFixed(1) + '" cy="' + yOf(r.elapsed).toFixed(1) +
          '" r="4" fill="#ca8a04" fill-opacity="0.85" stroke="#ca8a04"><title>' +
          esc(r.key + ' · в работе ' + fmt(r.elapsed) + ' дн. · ' + r.status + '\n' + r.title) +
          '</title></circle>');
      });
    }

    // точки: выбросы крупнее и красные
    pts.forEach(function (p) {
      parts.push('<circle cx="' + xOf(p.doneAt).toFixed(1) + '" cy="' + yOf(p.cycle).toFixed(1) +
        '" r="' + (p.outlier ? 4 : 3) + '" fill="' + (p.outlier ? '#dc2626' : '#16a34a') +
        '" fill-opacity="' + (p.outlier ? 0.85 : 0.5) + '" stroke="' + (p.outlier ? '#dc2626' : '#16a34a') +
        '" stroke-opacity="0.9"><title>' + esc(p.key + ' · ' + fmt(p.cycle) + ' дн. · ' + p.doneAt + '\n' + p.title) +
        '</title></circle>');
    });

    parts.push('<text x="' + padL + '" y="' + (H - 8) + '" font-size="10" fill="#666">' + esc(pts[0].doneAt) + '</text>');
    parts.push('<text x="' + (W - padR) + '" y="' + (H - 8) +
      '" font-size="10" fill="#666" text-anchor="end">' + esc(pts[pts.length - 1].doneAt) + '</text>');

    // список выбросов — то, ради чего диаграмма и нужна
    var outliers = pts.filter(function (p) { return p.outlier; })
      .sort(function (a, b) { return b.cycle - a.cycle; });
    var listHtml = '';
    if (outliers.length) {
      listHtml += '<div class="outliers"><div class="outliers-head">Выбиваются из коридора (' +
        outliers.length + ' из ' + pts.length + ')</div>' +
        outliers.map(function (p) {
          return '<div class="outlier-row"' + ctxAttr(chartItemTarget(p, kind)) + '>' +
            '<a href="' + jiraUrl(p.key) + '" target="_blank" rel="noopener" title="' + esc(p.key + ' — ' + p.title) + '">' +
              '<span class="key">' + esc(p.key) + '</span>' + esc(p.title) + '</a>' +
            '<span class="status ' + bucketClass(p.status, p.category) + '" title="' + esc(p.status) + '">' + esc(p.status) + '</span>' +
            '<span class="age stale">' + fmt(p.cycle) + ' д</span>' +
            '</div>';
        }).join('') + '</div>';
    }
    if (c.risks && c.risks.length) {
      listHtml += '<div class="outliers"><div class="outliers-head risk">В зоне риска (' + c.risks.length +
        ') — в работе дольше медианы ' + fmt(c.median) + ' дн.</div>' +
        c.risks.map(function (r) {
          return '<div class="outlier-row"' + ctxAttr(chartItemTarget(r, kind)) + '>' +
            '<a href="' + jiraUrl(r.key) + '" target="_blank" rel="noopener" title="' + esc(r.key + ' — ' + r.title) + '">' +
              '<span class="key">' + esc(r.key) + '</span>' + esc(r.title) + '</a>' +
            '<span class="status ' + bucketClass(r.status, r.category) + '" title="' + esc(r.status) + '">' + esc(r.status) + '</span>' +
            '<span class="age risk">' + fmt(r.elapsed) + ' д</span>' +
            '</div>';
        }).join('') + '</div>';
    }

    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' +
      parts.join('') + '</svg>' +
      '<div class="chart-legend">' +
        '<span class="swatch"></span>скользящее среднее &nbsp; ' +
        '<span class="swatch limit"></span>порог выброса ' + fmt(c.limit) + ' дн. &nbsp; ' +
        '<span class="dot" style="background:var(--c-testing)"></span>в зоне риска' +
        (overflow > 0 ? ' (' + overflow + ' выше шкалы)' : '') +
      '</div>' + listHtml;
  }

  // ------------------ Производительность: запланировано / сделано ------------------
  // Плановый столбец разложен по текущим статусам — видно, где осело незакрытое.
  function velocityChart(data) {
    var v = data || VELOCITY;
    if (!v || !v.sprints || !v.sprints.length) return '<div class="m-muted">Нет данных по спринтам.</div>';

    var rows = v.sprints;
    var W = (CHART_BOX && CHART_BOX.W) || 560, H = (CHART_BOX && CHART_BOX.H) || 210, padL = 34, padR = 14, padT = 12, padB = 30;
    var innerW = W - padL - padR, innerH = H - padT - padB;
    var maxY = Math.max.apply(null, rows.map(function (r) { return Math.max(r.planned, r.done); })) || 1;
    var yOf = function (val) { return padT + innerH * (1 - val / maxY); };
    var group = innerW / rows.length;
    var barW = Math.min(38, group / 3);

    var parts = [];
    [0, Math.round(maxY / 2), maxY].forEach(function (val) {
      parts.push('<line x1="' + padL + '" y1="' + yOf(val).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + yOf(val).toFixed(1) + '" stroke="#eee"/>');
      parts.push('<text x="4" y="' + (yOf(val) + 4).toFixed(1) + '" font-size="10" fill="#666">' + val + '</text>');
    });

    var STACK = [
      { id: 'open',     label: 'TODO',          color: 'var(--c-open)' },
      { id: 'blocked',  label: 'Заблокировано', color: 'var(--c-blocked)' },
      { id: 'progress', label: 'В работе',      color: 'var(--c-progress)' },
      { id: 'testing',  label: 'Тестирование',  color: 'var(--c-testing)' },
      { id: 'review',   label: 'Ревью',         color: 'var(--c-review)' },
      { id: 'done',     label: 'Готово',        color: 'var(--c-done)' }
    ];

    rows.forEach(function (r, i) {
      var cx = padL + group * i + group / 2;
      var xPlan = cx - barW - 3, xDone = cx + 3;

      // плановый столбец — стопка по статусам снизу вверх
      var acc = 0;
      STACK.forEach(function (seg) {
        var n = (r.split && r.split[seg.id]) || 0;
        if (!n) return;
        var yTop = yOf(acc + n), yBot = yOf(acc);
        parts.push('<rect x="' + xPlan.toFixed(1) + '" y="' + yTop.toFixed(1) +
          '" width="' + barW.toFixed(1) + '" height="' + Math.max(0, yBot - yTop).toFixed(1) +
          '" fill="' + seg.color + '" fill-opacity="0.85"><title>' +
          esc(r.name + ' · ' + seg.label + ': ' + n) + '</title></rect>');
        acc += n;
      });

      // столбец «сделано»
      parts.push('<rect x="' + xDone.toFixed(1) + '" y="' + yOf(r.done).toFixed(1) +
        '" width="' + barW.toFixed(1) + '" height="' + Math.max(0, yOf(0) - yOf(r.done)).toFixed(1) +
        '" fill="var(--c-done)"><title>' + esc(r.name + ' · сделано: ' + r.done) + '</title></rect>');

      parts.push('<text x="' + cx.toFixed(1) + '" y="' + (H - 8) +
        '" font-size="10" fill="#666" text-anchor="middle">' + esc(r.name) + '</text>');
    });

    // линия среднего выполнения
    if (v.avgDone) {
      parts.push('<line x1="' + padL + '" y1="' + yOf(v.avgDone).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + yOf(v.avgDone).toFixed(1) + '" stroke="#111" stroke-width="1.5" stroke-dasharray="4 3"/>');
    }

    var legend = STACK.map(function (seg) {
      return '<span class="dot" style="background:' + seg.color + '"></span>' + esc(seg.label);
    }).join(' &nbsp; ');

    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' +
      parts.join('') + '</svg>' +
      '<div class="chart-legend">' + legend + '</div>';
  }

  // ------------------ лента: общие помощники (отчёт PO и сайдбар истории в колоде) ------------------
  function relTime(iso) {
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + ' мин назад';
    if (diff < 86400) return Math.round(diff / 3600) + ' ч назад';
    var d = new Date(iso);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }

  function dayLabel(iso) {
    var d = new Date(iso), today = new Date();
    var same = function (a, b) { return a.toDateString() === b.toDateString(); };
    var yest = new Date(today.getTime() - 86400000);
    if (same(d, today)) return 'Сегодня';
    if (same(d, yest)) return 'Вчера';
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  }

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/);
    return parts.slice(0, 2).map(function (p) { return p.charAt(0).toUpperCase(); }).join('');
  }

  // Тип события определяет, что показываем в строке ленты.
  var LOG_KINDS = [
    { id: 'status',  label: 'Смена статуса' },
    { id: 'comment', label: 'Комментарий' },
    { id: 'created', label: 'Создание' }
  ];

  function logEventBody(e) {
    if (e.kind === 'comment') {
      return '<div class="log-move"><span class="log-verb">оставил комментарий</span></div>' +
        '<div class="log-quote">' + esc(e.body || '') + '</div>';
    }
    if (e.kind === 'created') {
      return '<div class="log-move"><span class="log-verb">создал</span>' +
        '<span class="status b-open">' + esc(e.issueType || 'задачу') + '</span></div>';
    }
    return '<div class="log-move">' +
      '<span class="status b-open">' + esc(e.from) + '</span>' +
      '<span class="arrow">→</span>' +
      '<span class="status ' + bucketClass(e.to, e.toCat) + '">' + esc(e.to) + '</span>' +
    '</div>';
  }

  function closePanels() {
    closeCommentPopup();
    overlay.classList.remove('open');
    panelStack.classList.remove('open');
  }

  overlay.addEventListener('click', closePanels);
  document.querySelectorAll('[data-close]').forEach(function (btn) {
    btn.addEventListener('click', closePanels);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (!cpop.hidden) { closeCommentPopup(); return; }  // сначала поле заметки
    if (notesPanel.classList.contains('open')) { setNotesOpen(false); return; }  // потом корзина
    closePanels();
  });

  // корзина: открыть/закрыть, новая заметка, промт
  notesToggle.addEventListener('click', function () {
    setNotesOpen(!notesPanel.classList.contains('open'));
    if (notesPanel.classList.contains('open')) { renderNotes(); document.getElementById('nText').focus(); }
  });
  var nText = document.getElementById('nText'), nRef = document.getElementById('nRef');
  var nCompose = document.getElementById('nCompose');
  function syncCompose() {
    nCompose.classList.toggle('filled', !!(nText.value || nRef.value));
    nText.style.height = 'auto';
    nText.style.height = Math.min(nText.scrollHeight + 2, 160) + 'px';
  }
  function addFromBasket() {
    if (addComment(resolveRef(nRef.value), nText.value)) { nText.value = ''; nRef.value = ''; syncCompose(); nText.focus(); }
  }
  nText.addEventListener('input', syncCompose);
  nRef.addEventListener('input', syncCompose);
  [nText, nRef].forEach(function (el) {
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); addFromBasket(); }
    });
  });

  var copyBtn = document.getElementById('copyBtn');
  copyBtn.addEventListener('click', function () {
    var text = document.getElementById('promptOut').value;
    if (!text) return;
    copyText(text).then(function () {
      copyBtn.textContent = 'Скопировано ✓';
    }, function () {
      var view = document.getElementById('promptOut');
      view.classList.add('open'); view.select();
      copyBtn.textContent = 'Выделено — Ctrl+C';
    }).then(function () {
      setTimeout(function () { copyBtn.textContent = 'Скопировать промт для ИИ'; }, 1600);
    });
  });
  var promptShow = document.getElementById('promptShow');
  promptShow.innerHTML = svgIcon('eye');
  promptShow.addEventListener('click', function () {
    document.getElementById('promptOut').classList.toggle('open');
  });

  // ------------------ промт для второго отчёта ------------------
  // Страницы не открывают друг друга: у отчёта PO кнопка «Бизнес-отчёт», у бизнес-
  // отчёта — «Для техлидов»; обе дают промт, по которому агент соберёт второй отчёт
  // своим навыком на тех же данных.
  var genWrap = document.getElementById('genWrap');
  var genText = document.getElementById('genText');

  function openGenPrompt(title, sub, text) {
    document.getElementById('genTitle').textContent = title;
    document.getElementById('genSub').textContent = sub;
    genText.value = text;
    genWrap.hidden = false;
    genText.focus();
    genText.setSelectionRange(0, 0);
    genText.scrollTop = 0;
  }
  function closeGenPrompt() { genWrap.hidden = true; }
  document.getElementById('genClose').addEventListener('click', closeGenPrompt);
  genWrap.addEventListener('mousedown', function (e) { if (e.target === genWrap) closeGenPrompt(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !genWrap.hidden) { e.stopImmediatePropagation(); closeGenPrompt(); }
  }, true);
  document.getElementById('genCopy').addEventListener('click', function () {
    var btn = this;
    copyText(genText.value).then(function () { btn.textContent = 'Скопировано ✓'; }, function () {
      genText.select(); btn.textContent = 'Выделено — Ctrl+C';
    }).then(function () { setTimeout(function () { btn.textContent = 'Скопировать промт'; }, 1600); });
  });

  // контекст сбора для промта: команды, спринты, время данных
  function dataContext() {
    var at = TEAMS.map(function (t) { return t._meta && t._meta.collectedAt; }).filter(Boolean).sort()[0] || '';
    return [
      'Команды: ' + TEAMS.map(function (t) { return t.team + ' (' + t.slug + ') — ' + t.sprintName; }).join('; '),
      'Данные JIRA: reports/sprint-report.data.json' + (at ? ', собраны ' + at.slice(0, 16).replace('T', ' ') : '') +
        ' — общий снимок обоих отчётов; заново не собирать, если не попросили свежие'
    ];
  }

  // заметки всех команд из корзин — то, что PO отметил на этой странице
  function allNotesLines() {
    var cur = team.slug, lines = [];
    TEAMS.forEach(function (t) {
      useTeam(t.slug);
      loadComments().forEach(function (c) {
        var to = c.target && c.target.kind !== 'general' ? targetLine(c.target) : 'в целом';
        lines.push((lines.length + 1) + '. [' + t.team + ' · ' + to + '] ' + c.text);
      });
    });
    useTeam(cur);
    return lines;
  }

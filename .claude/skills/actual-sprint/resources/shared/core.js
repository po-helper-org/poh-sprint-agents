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
  function fmtNum(v) { return String(Math.round(v * 10) / 10).replace('.', ','); }
  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }
  function ddmm(iso) { return iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) : '—'; }
  function dayMs(iso) { return new Date(iso + 'T12:00:00').getTime(); }
  function addDays(iso, n) { return isoDay(new Date(dayMs(iso) + n * 86400000)); }
  function ddmmyy(iso) { return iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(2, 4) : '—'; }

  // Сгорание эпика по неделям — как отчёт JIRA «Epic burndown»: столбец на неделю,
  // сверху выполнено за неделю, ниже осталось, внизу добавлено; столбцы «висят» от
  // накопленного выполненного. Справа — серые прогнозные недели по темпу последних
  // трёх недель и панель: сколько недель до закрытия, прогноз и план (срок эпика).
  var BURN_WEEKS = 10, BURN_FORECAST = 8;

  // Основа расчёта: SP задач эпика, закрытие историй (задач эпика) или всех подзадач.
  var BURN_MODES = [
    { id: 'sp', label: 'SP', unit: 'SP' },
    { id: 'stories', label: 'Закрытие историй', unit: 'ист.' },
    { id: 'subtasks', label: 'Закрытие подзадач', unit: 'подз.' }
  ];
  var burnMode = null;           // выбор PO — один на страницу, переживает переключение эпиков
  var BURN_REFS = [];

  // единицы сгорания: [{created, doneAt, w}] — вес 1 у истории и подзадачи, SP у оценки
  function burnUnits(epic, mode, today) {
    var scope = epic.scope || [];
    var isDone = function (x) { return classifyBucket(x.status, x.category) === 'done'; };
    var unit = function (x, w) { return { created: x.created, doneAt: isDone(x) ? (x.doneAt || today) : null, w: w }; };
    if (mode === 'subtasks') {
      return scope.reduce(function (a, it) { return a.concat((it.subtasks || []).filter(function (s) { return s.created; }).map(function (s) { return unit(s, 1); })); }, []);
    }
    var items = scope.filter(function (it) { return it.created; });
    if (mode === 'sp') return items.filter(function (it) { return it.sp; }).map(function (it) { return unit(it, it.sp); });
    return items.map(function (it) { return unit(it, 1); });
  }

  function epicBurn(t, epic, mode) {
    var today = ((t._meta && t._meta.collectedAt) || new Date().toISOString()).slice(0, 10);
    var units = burnUnits(epic, mode, today);
    if (!units.length) return null;
    var sum = function (list) { return list.reduce(function (a, u) { return a + u.w; }, 0); };
    var start = units.map(function (u) { return u.created; }).sort()[0];
    var weeks = Math.max(1, Math.ceil((dayMs(today) - dayMs(start) + 86400000) / (7 * 86400000)));
    var shown = Math.min(weeks, BURN_WEEKS);
    var base = addDays(today, -7 * shown);
    var openAt = function (d) { return sum(units.filter(function (u) { return u.created <= d && !(u.doneAt && u.doneAt <= d); })); };
    var bars = [{ label: weeks > shown ? 'до ' + ddmm(base) : 'начало', to: base, done: 0, left: openAt(base), added: 0, top: 0, base: true }];
    var top = 0;
    for (var k = shown - 1; k >= 0; k--) {
      var from = addDays(today, -7 * (k + 1)), to = addDays(today, -7 * k);
      var inP = function (d) { return d && d > from && d <= to; };
      var done = sum(units.filter(function (u) { return inP(u.doneAt); }));
      var addedOpen = sum(units.filter(function (u) { return inP(u.created) && !(u.doneAt && u.doneAt <= to); }));
      var added = sum(units.filter(function (u) { return inP(u.created); }));
      bars.push({ label: ddmm(to), from: from, to: to, done: done, left: openAt(to) - addedOpen, added: addedOpen, addedAll: added, top: top, current: k === 0 });
      top += done;
    }
    var remaining = openAt(today);
    var hist = bars.filter(function (b) { return !b.base; });
    var recent = hist.slice(-3);
    var pace = sum(recent.map(function (b) { return { w: b.done }; })) / Math.max(1, recent.length);
    var paceBasis = 'последние ' + recent.length + ' нед.';
    if (!pace) { pace = sum(hist.map(function (b) { return { w: b.done }; })) / Math.max(1, hist.length); paceBasis = 'за ' + hist.length + ' нед.'; }
    var weeksLeft = remaining ? (pace ? Math.ceil(remaining / pace) : null) : 0;
    var meta = BURN_MODES.find(function (m) { return m.id === mode; });
    var unestimated = mode === 'sp' ? (epic.scope || []).filter(function (it) { return it.created && !it.sp; }).length : 0;
    return { mode: mode, unit: meta.unit, today: today, total: sum(units), done: sum(units) - remaining, remaining: remaining,
             bars: bars, top: top, pace: pace, paceBasis: paceBasis, weeksLeft: weeksLeft, unestimated: unestimated,
             count: (epic.scope || []).filter(function (it) { return it.created; }).length,
             forecast: weeksLeft === null ? null : addDays(today, 7 * weeksLeft), due: epic.epicDue || null };
  }

  function epicBurnChart(b) {
    var fc = [];
    if (b.weeksLeft) {
      var rem = b.remaining, top = b.top;
      for (var k = 1; k <= Math.min(b.weeksLeft, BURN_FORECAST); k++) {
        var step = Math.min(b.pace, rem);
        fc.push({ label: '+' + k, to: addDays(b.today, 7 * k), top: top, done: step, left: rem - step });
        top += step; rem -= step;
      }
    }
    var cols = b.bars.length + fc.length + (b.weeksLeft > BURN_FORECAST ? 1 : 0);
    var W = 760, H = 300, padL = 10, padR = 8, padT = 24, padB = 34;
    var colW = (W - padL - padR) / cols, barW = Math.min(40, colW * 0.62);
    var maxY = Math.max.apply(null, b.bars.map(function (x) { return x.top + x.done + x.left + x.added; })
      .concat(fc.map(function (x) { return x.top + x.done + x.left; }))) || 1;
    var yOf = function (v) { return padT + (H - padT - padB) * v / maxY; };
    var parts = [];
    parts.push('<line x1="' + padL + '" x2="' + (W - padR) + '" y1="' + padT + '" y2="' + padT + '" stroke="#e5e5e5"/>');
    var seg = function (x, v0, v, fill, label, color, tip) {
      if (v <= 0) return;
      var y0 = yOf(v0), h = yOf(v0 + v) - y0;
      parts.push('<rect x="' + x.toFixed(1) + '" y="' + y0.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(1, h).toFixed(1) +
        '" fill="' + fill + '"><title>' + esc(tip) + '</title></rect>');
      if (label && h >= 13) parts.push('<text x="' + (x + barW / 2).toFixed(1) + '" y="' + (y0 + h / 2 + 4).toFixed(1) +
        '" font-size="11" font-weight="700" fill="' + color + '" text-anchor="middle">' + label + '</text>');
    };
    var xAt = function (i) { return padL + colW * i + (colW - barW) / 2; };
    b.bars.forEach(function (x, i) {
      var cx = xAt(i), when = x.base ? x.label : 'неделя по ' + x.label;
      seg(cx, x.top, x.done, '#cfe8c4', '−' + fmtNum(x.done), '#2f7a2f', when + ': выполнено ' + fmtNum(x.done) + ' ' + b.unit);
      seg(cx, x.top + x.done, x.left, '#6c9fd8', fmtNum(x.left), '#fff', when + ': осталось ' + fmtNum(x.left) + ' ' + b.unit);
      seg(cx, x.top + x.done + x.left, x.added, '#3f6290', '+' + fmtNum(x.added), '#fff', when + ': добавлено ' + fmtNum(x.addedAll || x.added) + ' ' + b.unit + (x.addedAll > x.added ? ', из них закрыто сразу ' + fmtNum(x.addedAll - x.added) : ''));
      parts.push('<text x="' + (cx + barW / 2).toFixed(1) + '" y="' + (H - 18) + '" font-size="10" fill="#555" text-anchor="middle">' + esc(x.label) + '</text>');
      if (x.current) parts.push('<text x="' + (cx + barW / 2).toFixed(1) + '" y="' + (H - 6) + '" font-size="9.5" fill="#888" text-anchor="middle">сейчас</text>');
    });
    var sepX = padL + colW * b.bars.length;
    parts.push('<line x1="' + sepX.toFixed(1) + '" x2="' + sepX.toFixed(1) + '" y1="' + (padT - 12) + '" y2="' + (H - padB) + '" stroke="#999" stroke-dasharray="4 4"/>');
    fc.forEach(function (x, i) {
      var cx = xAt(b.bars.length + i);
      seg(cx, x.top, x.done, '#d4d4d4', '', '#555', 'прогноз, неделя по ' + ddmm(x.to) + ': закрыть ≈ ' + fmtNum(x.done));
      seg(cx, x.top + x.done, x.left, '#ececec', '', '#555', 'прогноз, неделя по ' + ddmm(x.to) + ': останется ≈ ' + fmtNum(x.left));
      parts.push('<text x="' + (cx + barW / 2).toFixed(1) + '" y="' + (H - 18) + '" font-size="10" fill="#999" text-anchor="middle">' + ddmm(x.to) + '</text>');
    });
    if (b.weeksLeft > BURN_FORECAST) {
      parts.push('<text x="' + (padL + colW * (cols - 0.5)).toFixed(1) + '" y="' + yOf(b.top + b.remaining / 2).toFixed(1) +
        '" font-size="10.5" fill="#999" text-anchor="middle">ещё ' + (b.weeksLeft - BURN_FORECAST) + ' нед.</text>');
    }
    // план: срок эпика — вертикаль в своей неделе
    if (b.due) {
      var ends = b.bars.filter(function (x) { return !x.base; }).map(function (x) { return x.to; }).concat(fc.map(function (x) { return x.to; }));
      var idx = ends.findIndex(function (d) { return b.due <= d; });
      var px = idx === -1 ? W - padR - 2 : padL + colW * (idx + 1) + colW * Math.min(1, Math.max(0, 1 - (dayMs(ends[idx]) - dayMs(b.due)) / (7 * 86400000)));
      parts.push('<line x1="' + px.toFixed(1) + '" x2="' + px.toFixed(1) + '" y1="' + (padT - 12) + '" y2="' + (H - padB) + '" stroke="#dc2626" stroke-width="1.5"/>');
      parts.push('<text x="' + Math.min(px, W - 40).toFixed(1) + '" y="' + (padT - 14) + '" font-size="10.5" fill="#dc2626" text-anchor="middle">план ' + ddmm(b.due) + (idx === -1 ? ' →' : '') + '</text>');
    }
    parts.push('<text x="' + (sepX + 4).toFixed(1) + '" y="' + (padT - 4) + '" font-size="10" fill="#888">прогноз</text>');
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' + parts.join('') + '</svg>';
  }

  function burnDefault(epic) {
    var hasSp = (epic.scope || []).some(function (it) { return it.sp; });
    return burnMode && (burnMode !== 'sp' || hasSp) ? burnMode : (hasSp ? 'sp' : 'stories');
  }

  // Сгорание эпика: переключатель основы, график по неделям и под ним — панель анализа.
  function epicBurnHtml(t, epic, ref) {
    if (ref === undefined) { BURN_REFS.push({ t: t, epic: epic }); ref = BURN_REFS.length - 1; }
    var mode = burnDefault(epic);
    var b = epicBurn(t, epic, mode);
    var tabs = '<div class="eb-modes" role="tablist">' + BURN_MODES.map(function (m) {
      return '<button type="button" role="tab" class="eb-mode' + (m.id === mode ? ' on' : '') + '" data-burn-mode="' + m.id + '" aria-selected="' + (m.id === mode) + '">' + m.label + '</button>';
    }).join('') + '</div>';
    var head = '<div class="eb-top"><div class="eb-title">Сгорание эпика</div>' + tabs + '</div>';
    if (!b) {
      var why = mode === 'sp' ? 'У задач эпика нет оценки в SP.' : mode === 'subtasks' ? 'Нет подзадач с датами: нужен сборщик 1.6.0+.' : 'Нет дат задач эпика: нужен сборщик 1.4.0+.';
      return '<div class="eb" data-burn="' + ref + '">' + head + '<div class="sidebar-empty">' + why + '</div></div>';
    }
    var u = b.unit;
    var diff = b.due && b.forecast ? Math.round((dayMs(b.forecast) - dayMs(b.due)) / 86400000) : null;
    // итог — число дней цветом: зелёный в срок, жёлтый опоздание до 7 дней, красный больше
    var tone = !b.remaining ? 'ok' : diff === null ? '' : diff <= 0 ? 'ok' : diff <= 7 ? 'warn' : 'bad';
    var verdictTip = !b.remaining ? 'Эпик выполнен'
      : b.weeksLeft === null ? 'Нет темпа: задачи не закрываются — прогноз не построить'
      : diff === null ? 'Срок эпика в JIRA не задан — сравнить не с чем'
      : diff <= 0 ? 'В темпе: запас ' + (-diff) + ' дн. до плановой даты'
      : diff <= 7 ? 'В риске: опоздание ' + diff + ' дн.' : 'Опоздание ' + diff + ' дн.';
    var verdict = !b.remaining ? 'готов' : diff === null ? '—' : Math.abs(diff) + ' дн.';
    var cell = function (big, label, tip, cls) {
      return '<div class="ea-cell' + (cls ? ' ' + cls : '') + '" title="' + esc(tip || '') + '"><span class="ea-label">' + label + '</span><b>' + big + '</b></div>';
    };
    var weeksTxt = b.weeksLeft ? '≈ ' + b.weeksLeft + ' ' + plural(b.weeksLeft, 'неделя', 'недели', 'недель') + ' до закрытия' : '';
    var analysis = '<div class="eb-analysis">' +
      cell(b.due ? ddmmyy(b.due) : '—', 'Плановая дата', b.due ? 'Срок эпика в JIRA' : 'Срок эпика в JIRA не задан') +
      cell(b.remaining ? (b.forecast ? ddmmyy(b.forecast) : '—') : 'готов', 'Расчётная дата',
           b.remaining ? (b.forecast ? weeksTxt + ' при темпе ' + fmtNum(b.pace) + ' ' + u + '/нед.' : 'Нет темпа') : 'Эпик выполнен', tone === 'ok' ? '' : tone) +
      cell(fmtNum(b.pace) + ' <small>' + u + '/нед.</small>', 'Темп сгорания', 'Среднее выполненное, ' + b.paceBasis) +
      cell(fmtNum(b.remaining) + ' <small>из ' + fmtNum(b.total) + ' ' + u + '</small>', 'Осталось',
           b.unestimated ? b.unestimated + ' ' + plural(b.unestimated, 'задача', 'задачи', 'задач') + ' без оценки — в SP не учтены' : '') +
      cell(verdict, 'Итог', verdictTip, 'verdict ' + tone) + '</div>';
    return '<div class="eb" data-burn="' + ref + '">' + head + epicBurnChart(b) +
      '<div class="eb-legend"><span><i class="l-done"></i>выполнено</span><span><i class="l-left"></i>осталось</span>' +
      '<span><i class="l-add"></i>добавлено</span><span><i class="l-fc"></i>прогноз</span>' + (b.due ? '<span><i class="l-due"></i>план</span>' : '') + '</div>' +
      analysis + '</div>';
  }

  // переключение основы: перерисовать только этот блок
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-burn-mode]');
    if (!btn) return;
    var box = btn.closest('[data-burn]'), ref = BURN_REFS[+box.dataset.burn];
    if (!ref) return;
    burnMode = btn.dataset.burnMode;
    box.outerHTML = epicBurnHtml(ref.t, ref.epic, +box.dataset.burn);
  });

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

  // ------------------ Burndown текущего спринта ------------------
  // Показывает, сколько задач ещё не закрыто по дням спринта.
  // scope пересчитывается по changelog поля Sprint, поэтому внесённые и
  // вынесенные из спринта задачи видны как ступеньки серой линии объёма.
  function burndownChart() {
    var b = BURNDOWN;
    if (!b || !b.days || !b.days.length) return '<div class="m-muted">Нет данных по спринту.</div>';

    var days = b.days;
    var W = (CHART_BOX && CHART_BOX.W) || 560, H = (CHART_BOX && CHART_BOX.H) || 210, padL = 34, padR = 14, padT = 12, padB = 30;
    var maxY = Math.max.apply(null, days.map(function (d) { return d.scope; })) || 1;
    var innerW = W - padL - padR, innerH = H - padT - padB;
    var xOf = function (i) { return padL + innerW * (days.length > 1 ? i / (days.length - 1) : 0); };
    var yOf = function (v) { return padT + innerH * (1 - v / maxY); };

    var parts = [];

    // выходные — светлые полосы
    days.forEach(function (d, i) {
      if (!d.weekend) return;
      var x1 = xOf(i) - innerW / (days.length - 1) / 2;
      var x2 = xOf(i) + innerW / (days.length - 1) / 2;
      parts.push('<rect x="' + Math.max(padL, x1).toFixed(1) + '" y="' + padT +
        '" width="' + Math.max(0, Math.min(W - padR, x2) - Math.max(padL, x1)).toFixed(1) +
        '" height="' + innerH + '" fill="#f4f4f5"/>');
    });

    // сетка и ось Y
    [0, Math.round(maxY / 2), maxY].forEach(function (v) {
      parts.push('<line x1="' + padL + '" y1="' + yOf(v).toFixed(1) + '" x2="' + (W - padR) +
        '" y2="' + yOf(v).toFixed(1) + '" stroke="#eee"/>');
      parts.push('<text x="4" y="' + (yOf(v) + 4).toFixed(1) + '" font-size="10" fill="#666">' + v + '</text>');
    });

    // идеальная линия: от объёма на старте до нуля в конце
    parts.push('<line x1="' + xOf(0) + '" y1="' + yOf(days[0].scope).toFixed(1) +
      '" x2="' + xOf(days.length - 1) + '" y2="' + yOf(0).toFixed(1) +
      '" stroke="#9ca3af" stroke-width="2"/>');

    // фактический остаток — только по сегодняшний день
    var actual = days.filter(function (d) { return !d.future; });
    if (actual.length) {
      var path = actual.map(function (d, i) {
        return (i ? 'L' : 'M') + xOf(i).toFixed(1) + ' ' + yOf(d.remaining).toFixed(1);
      }).join(' ');
      parts.push('<path d="' + path + '" fill="none" stroke="#dc2626" stroke-width="2"/>');
      actual.forEach(function (d, i) {
        parts.push('<circle cx="' + xOf(i).toFixed(1) + '" cy="' + yOf(d.remaining).toFixed(1) +
          '" r="2.5" fill="#dc2626"><title>' + esc(d.date + ': осталось ' + d.remaining +
          ' из ' + d.scope + ', закрыто ' + d.closed) + '</title></circle>');
      });
    }

    // подписи крайних дат
    parts.push('<text x="' + padL + '" y="' + (H - 8) + '" font-size="10" fill="#666">' + esc(b.start) + '</text>');
    parts.push('<text x="' + (W - padR) + '" y="' + (H - 8) +
      '" font-size="10" fill="#666" text-anchor="end">' + esc(b.end) + '</text>');

    var last = actual.length ? actual[actual.length - 1] : days[0];
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' +
      parts.join('') + '</svg>' +
      '<div class="chart-legend">' +
        '<span class="swatch ideal"></span>идеальный темп &nbsp; ' +
        '<span class="swatch actual"></span>фактический остаток<br>' +
        'Сейчас закрыто <b>' + last.closed + '</b> из <b>' + last.scope + '</b>, осталось <b>' +
        last.remaining + '</b>.' +
      '</div>';
  }

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

  // ---------- участники: выработка по спринтам (отчёт PO — «Команда: N») ----------
  // Три группы статусов вместо шести: так строку участника можно прочитать с экрана.
  // Раскладка внутри группы — по наведению.
  var CANCEL_RE = /отмен|отклон|cancel|reject|won.?t/i;
  var OUT_GROUPS = [
    { id: 'todo', label: 'Не начато', color: 'var(--c-open)',
      parts: [{ label: 'Backlog / To Do', b: 'open' }, { label: 'В блоке', b: 'blocked' }] },
    { id: 'work', label: 'В работе', color: 'var(--c-progress)',
      parts: [{ label: 'В работе', b: 'progress' }, { label: 'Ревью', b: 'review' }, { label: 'Отладка', b: 'testing' }] },
    { id: 'done', label: 'Выполнено', color: 'var(--c-done)',
      parts: [{ label: 'Готово', b: 'done', cancel: false }, { label: 'Отменено', b: 'done', cancel: true }] }
  ];


  var OUT_TIPS = [];      // расшифровки ячеек: data-tip — индекс
  var MEMBER_REFS = [];   // участник по клику: data-member — индекс

  function shortName(name) {
    var parts = String(name || '').trim().split(/\s+/);
    if (parts.length < 2 || name === 'Не назначен') return name;
    return parts[0] + ' ' + parts.slice(1, 3).map(function (x) { return x.charAt(0).toUpperCase() + '.'; }).join(' ');
  }


  // ячейка участника за спринт: группы → части → [задач, SP]; отменённое — по имени статуса
  function memberCell(m) {
    if (!m) return null;
    var parts = {};
    OUT_GROUPS.forEach(function (g) { g.parts.forEach(function (pt, i) { parts[g.id + i] = [0, 0]; }); });
    var put = function (b, cancel, n, sp) {
      OUT_GROUPS.forEach(function (g) {
        g.parts.forEach(function (pt, i) {
          if (pt.b === b && (pt.cancel === undefined || pt.cancel === cancel)) { parts[g.id + i][0] += n; parts[g.id + i][1] += sp; }
        });
      });
    };
    if (m.items) m.items.forEach(function (it) { put(it.bucket, it.bucket === 'done' && CANCEL_RE.test(it.status), 1, it.sp || 0); });
    else Object.keys(m.split).forEach(function (b) { put(b, false, m.split[b][0], m.split[b][1]); });
    var groups = {};
    OUT_GROUPS.forEach(function (g) {
      groups[g.id] = g.parts.reduce(function (a, pt, i) { return [a[0] + parts[g.id + i][0], a[1] + parts[g.id + i][1]]; }, [0, 0]);
    });
    return { parts: parts, groups: groups };
  }

  function sumCells(cells) {
    var out = null;
    cells.forEach(function (c) {
      if (!c) return;
      if (!out) out = JSON.parse(JSON.stringify(c));
      else {
        Object.keys(c.parts).forEach(function (k) { out.parts[k][0] += c.parts[k][0]; out.parts[k][1] += c.parts[k][1]; });
        Object.keys(c.groups).forEach(function (k) { out.groups[k][0] += c.groups[k][0]; out.groups[k][1] += c.groups[k][1]; });
      }
    });
    return out;
  }

  function outputModel(t) {
    var out = t.output;
    if (!out || !out.sprints || !out.sprints.length) return null;
    var sprints = out.sprints.slice(-3);
    var names = {};
    sprints.forEach(function (s) { s.members.forEach(function (m) { names[m.name] = true; }); });
    var sp = !!out.field;
    var rows = Object.keys(names).map(function (name) {
      var members = sprints.map(function (s) { return s.members.find(function (x) { return x.name === name; }) || null; });
      var cells = members.map(memberCell);
      var doneSum = cells.reduce(function (a, c) { return a + (c ? c.groups.done[sp ? 1 : 0] : 0); }, 0);
      return { name: name, members: members, cells: cells, doneSum: doneSum, lead: (out.lead || {})[name] || null };
    });
    rows.sort(function (a, b) {
      if ((a.name === 'Не назначен') !== (b.name === 'Не назначен')) return a.name === 'Не назначен' ? 1 : -1;
      return b.doneSum - a.doneSum || (a.name < b.name ? -1 : 1);
    });
    var team = sprints.map(function (s, i) { return sumCells(rows.map(function (r) { return r.cells[i]; })); });
    return { unit: sp ? 'SP' : 'задач', sp: sp, sprints: sprints, rows: rows, team: team };
  }

  // ячейка таблицы: выполнено крупно, полоса из трёх групп, расшифровка — по наведению
  function outCell(c, m, who, sprint) {
    if (!c) return '<td class="mcell"><span class="none">—</span></td>';
    var k = m.sp ? 1 : 0, g = c.groups, total = g.todo[k] + g.work[k] + g.done[k];
    OUT_TIPS.push({ who: who, sprint: sprint.name, current: sprint.current, c: c, sp: m.sp });
    var bar = OUT_GROUPS.map(function (gr) {
      var w = total ? 100 * g[gr.id][k] / total : 0;
      return w ? '<i style="width:' + w.toFixed(1) + '%;background:' + gr.color + '"></i>' : '';
    }).join('');
    return '<td class="mcell" data-tip="' + (OUT_TIPS.length - 1) + '"><div class="mc-top"><b>' + fmtNum(g.done[k]) + '</b>' +
      '<span>' + (m.sp ? 'SP' : '') + ' из ' + fmtNum(total) + '</span></div><div class="mc-bar">' + bar + '</div>' +
      '<div class="mc-nums">' + OUT_GROUPS.map(function (gr) {
        return '<span class="g-' + gr.id + (g[gr.id][k] ? '' : ' z') + '">' + fmtNum(g[gr.id][k]) + '</span>';
      }).join('<span class="sep">·</span>') + '</div></td>';
  }

  function tipHtml(d) {
    var k = d.sp ? 1 : 0;
    var unit = function (n, sp) { return n + ' ' + plural(n, 'задача', 'задачи', 'задач') + (d.sp ? ' · ' + fmtNum(sp) + ' SP' : ''); };
    var html = OUT_GROUPS.map(function (g) {
      var gv = d.c.groups[g.id];
      return '<div class="tg"><div class="tr head' + (gv[0] ? '' : ' zero') + '"><i style="background:' + g.color + '"></i><span>' + g.label +
        '</span><span>' + unit(gv[0], gv[1]) + '</span></div>' + g.parts.map(function (pt, i) {
          var v = d.c.parts[g.id + i];
          return '<div class="tr sub' + (v[0] ? '' : ' zero') + '"><i></i><span>' + pt.label + '</span><span>' + unit(v[0], v[1]) + '</span></div>';
        }).join('') + '</div>';
    }).join('');
    return '<b>' + esc(d.who) + ' · ' + esc(d.sprint) + '</b>' + html +
      '<div class="sum">В зачёт — «Выполнено»' + (d.current ? ', на сейчас' : ', на конец спринта') + '</div>';
  }

  function memberTable(t, m, opts) {
    var head = '<tr><th style="width:118px">Участник</th>' + m.sprints.map(function (s, i) {
      var rel = m.sprints.length - 1 - i;
      return '<th>' + esc(s.name) + '<small>' + (rel ? 'S−' + rel : 'S · ' + (s.current ? 'сейчас' : 'последний')) + '</small></th>';
    }).join('') + '<th style="width:70px">Lead time<small>медиана</small></th></tr>';
    var body = m.rows.map(function (r) {
      MEMBER_REFS.push({ team: t, row: r, m: m, back: !!(opts && opts.back) });
      return '<tr><td class="who"><button type="button" class="mname" data-member="' + (MEMBER_REFS.length - 1) + '" title="Задачи участника за спринт">' +
        esc(shortName(r.name)) + '</button></td>' +
        r.cells.map(function (c, i) { return outCell(c, m, r.name, m.sprints[i]); }).join('') +
        '<td class="lead" title="' + (r.lead ? 'закрыто ' + r.lead.count + ' за спринты отчёта' : 'закрытых нет') + '">' +
        (r.lead ? fmtNum(r.lead.median) + ' дн.' : '—') + '</td></tr>';
    }).join('');
    var total = '<tr class="total"><td class="who">Команда</td>' + m.team.map(function (c, i) {
      return outCell(c, m, 'Команда', m.sprints[i]);
    }).join('') + '<td class="lead"></td></tr>';
    // много участников — плотнее: числа по группам остаются в подсказке
    return '<table class="mtab' + (m.rows.length > 7 ? ' dense' : '') + '"><thead>' + head + '</thead><tbody>' + body + total + '</tbody></table>';
  }

  // ---------- сайдбары поверх колоды ----------
  function sideTabs(tabs, active, render, head) {
    var bar = (head || '') + '<div class="side-tabs">' + tabs.map(function (t) {
      return '<button type="button" class="side-tab' + (t.id === active ? ' active' : '') + '" data-tab="' + t.id + '">' +
        esc(t.label) + ' · ' + t.n + '</button>';
    }).join('') + '</div>';
    storiesBody.innerHTML = bar + '<div class="side-body"></div>';
    var body = storiesBody.querySelector('.side-body');
    var show = function (id) {
      storiesBody.querySelectorAll('.side-tab').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === id); });
      body.innerHTML = '';
      render(id, body);
    };
    storiesBody.querySelectorAll('.side-tab').forEach(function (b) {
      b.addEventListener('click', function () { show(b.dataset.tab); });
    });
    show(active);
  }

  function openPanel() { overlay.classList.add('open'); panelStack.classList.add('open'); }

  // ---------- участник: его задачи за спринт и активность по задаче ----------
  function memberItemsHtml(items, sp) {
    // сначала то, что пошло в зачёт
    var groups = OUT_GROUPS.slice().reverse().map(function (g) {
      var list = items.filter(function (it) { return g.parts.some(function (pt) { return pt.b === it.bucket; }); });
      return { g: g, list: list };
    });
    return groups.map(function (x) {
      var spSum = x.list.reduce(function (a, it) { return a + (it.sp || 0); }, 0);
      return '<div class="mi-group"><div class="mi-head"><i style="background:' + x.g.color + '"></i>' + x.g.label +
        (x.g.id === 'done' ? ' — в зачёт' : '') + '<span>' + x.list.length + (sp ? ' · ' + fmtNum(spSum) + ' SP' : '') + '</span></div>' +
        (x.list.length ? x.list.map(function (it) {
          var i = items.indexOf(it);
          return '<button type="button" class="mi-row" data-item="' + i + '"><span class="mi-key">' + esc(it.key) + '</span>' +
            '<span class="mi-title">' + esc(it.title) + '</span><span class="status ' + bucketClass(it.status, '') + '">' + esc(it.status) + '</span>' +
            '<span class="mi-sp">' + (sp ? fmtNum(it.sp || 0) + ' SP' : '') + '</span></button>';
        }).join('') : '<div class="mi-empty">нет</div>') + '</div>';
    }).join('');
  }

  // коротко и по хронологии: смены статуса и комментарии задачи за спринт
  function itemActivityHtml(it) {
    var ev = (it.history || []).map(function (h) { return { at: h.at, by: h.by, h: h }; })
      .concat((it.comments || []).map(function (c) { return { at: c.at, by: c.by, c: c }; }))
      .sort(function (a, b) { return a.at < b.at ? -1 : 1; });
    if (!ev.length) return '<div class="mi-act-empty">За спринт ни смен статуса, ни комментариев.</div>';
    return '<ol class="mi-act">' + ev.map(function (e) {
      var when = e.at.slice(8, 10) + '.' + e.at.slice(5, 7) + ' ' + e.at.slice(11, 16);
      var what = e.c ? '<span class="mi-c">«' + esc(e.c.body) + '»</span>'
        : '<span class="status b-open">' + esc(e.h.from || '—') + '</span><span class="arrow">→</span><span class="status ' + bucketClass(e.h.to, '') + '">' + esc(e.h.to) + '</span>';
      return '<li class="' + (e.c ? 'is-c' : 'is-s') + '"><span class="mi-when">' + when + '</span><span class="mi-what">' + what +
        '</span><span class="mi-by" title="' + esc(e.by || '') + '">' + esc(initials(e.by || '—')) + '</span></li>';
    }).join('') + '</ol>';
  }

  function openMember(ref, sprintIdx) {
    if (team.slug !== ref.team.slug) switchTeam(ref.team.slug);
    var r = ref.row, m = ref.m;
    stackTitle.parentNode.removeAttribute('data-ctx');
    stackKey.textContent = 'Участник · ' + ref.team.team;
    stackTitle.textContent = r.name;
    scopeBtn.hidden = true;
    scopeEpic = null;
    storiesLabel.textContent = 'Задачи за спринт: что пошло в зачёт' + (m.sp ? ' · SP' : '');
    var tabs = m.sprints.map(function (s, i) {
      return { id: String(i), label: s.name, n: ((r.members[i] || {}).items || []).length };
    });
    var active = sprintIdx === undefined ? String(m.sprints.length - 1) : String(sprintIdx);
    // открыт из «Команды» (отчёт PO) — путь назад к таблице
    var back = ref.back && typeof openTeam === 'function' ? '<button type="button" class="mi-back" data-team-back>← Команда</button>' : '';
    sideTabs(tabs, active, function (id, body) {
      var mem = r.members[+id];
      var items = (mem && mem.items) || [];
      if (!items.length) { body.innerHTML = '<div class="sidebar-empty">' + (mem ? 'Список задач в данных нет: нужен сборщик 1.4.0+.' : 'В этом спринте задач нет.') + '</div>'; return; }
      // клик по задаче раскрывает под ней её историю за спринт, на том же экране
      body.innerHTML = memberItemsHtml(items, m.sp);
      body.querySelectorAll('.mi-row').forEach(function (b) {
        b.addEventListener('click', function () {
          var next = b.nextElementSibling;
          if (next && next.classList.contains('mi-detail')) { next.remove(); b.classList.remove('open'); return; }
          b.classList.add('open');
          b.insertAdjacentHTML('afterend', '<div class="mi-detail">' + itemActivityHtml(items[+b.dataset.item]) +
            '<a class="mi-jira" href="' + jiraUrl(items[+b.dataset.item].key) + '" target="_blank" rel="noopener">Открыть в JIRA ↗</a></div>');
        });
      });
    }, back);
    openPanel();
  }


  // расшифровка ячейки участника по наведению (на телефоне — по тапу)
  var deckTip = document.createElement('div');
  deckTip.className = 'deck-tip';
  deckTip.hidden = true;
  document.body.appendChild(deckTip);
  function placeTip(cell, x, y) {
    var d = OUT_TIPS[+cell.getAttribute('data-tip')];
    if (!d) return;
    deckTip.innerHTML = tipHtml(d);
    deckTip.hidden = false;
    var w = deckTip.offsetWidth, h = deckTip.offsetHeight;
    deckTip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + 'px';
    deckTip.style.top = Math.max(8, y + 16 + h > innerHeight ? y - h - 12 : y + 16) + 'px';
  }
  document.addEventListener('mousemove', function (e) {
    var cell = e.target.closest && e.target.closest('[data-tip]');
    if (!cell) { if (!deckTip.hidden) deckTip.hidden = true; return; }
    placeTip(cell, e.clientX, e.clientY);
  });
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-team-back]')) { openTeam(); return; }
    var mb = e.target.closest && e.target.closest('[data-member]');
    if (mb) { deckTip.hidden = true; openMember(MEMBER_REFS[+mb.dataset.member]); return; }
    var cell = e.target.closest && e.target.closest('[data-tip]');
    if (!cell) { deckTip.hidden = true; return; }
    var r = cell.getBoundingClientRect();
    placeTip(cell, r.left, r.bottom - 10);
  });
  document.addEventListener('scroll', function () { deckTip.hidden = true; }, true);

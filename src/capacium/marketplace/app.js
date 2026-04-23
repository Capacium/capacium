(function () {
  'use strict';

  var API_BASE = window.CAPACIUM_API || '/v1';

  var state = {
    capabilities: [],
    filtered: [],
    selected: null,
    filters: { kind: '', framework: '' },
    searchQuery: '',
  };

  var els = {};

  function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
  function qsa(sel, ctx) { return (ctx || document).querySelectorAll(sel); }

  function init() {
    els.searchInput = document.getElementById('search-input');
    els.cardGrid = document.getElementById('card-grid');
    els.resultCount = document.getElementById('result-count');
    els.modal = document.getElementById('detail-modal');
    els.modalBody = document.getElementById('modal-body');
    els.modalClose = document.getElementById('modal-close');

    els.searchInput.addEventListener('input', onSearch);

    qsa('.chip[data-filter]').forEach(function (chip) {
      chip.addEventListener('click', onFilterClick);
    });

    els.modalClose.addEventListener('click', closeModal);
    els.modal.addEventListener('click', function (e) {
      if (e.target === els.modal) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeModal();
    });

    loadCapabilities();
  }

  function onSearch() {
    state.searchQuery = els.searchInput.value.trim().toLowerCase();
    applyFilters();
  }

  function onFilterClick(e) {
    var chip = e.currentTarget;
    var filter = chip.dataset.filter;
    var value = chip.dataset.value;

    var siblings = qsa('.chip[data-filter="' + filter + '"]');
    siblings.forEach(function (s) { s.classList.remove('active'); });
    chip.classList.add('active');

    state.filters[filter] = value;
    applyFilters();
  }

  function loadCapabilities() {
    var url = API_BASE + '/capabilities';

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        state.capabilities = data.results || [];
        applyFilters();
      })
      .catch(function (err) {
        els.cardGrid.innerHTML =
          '<div class="empty-state">' +
          '<div class="empty-state-icon">\u26A0</div>' +
          '<div class="empty-state-text">Failed to load capabilities</div>' +
          '<div style="font-size:12px;color:var(--text-muted)">' + err.message + '</div>' +
          '</div>';
      });
  }

  function applyFilters() {
    var query = state.searchQuery;
    var kind = state.filters.kind;
    var framework = state.filters.framework;

    state.filtered = state.capabilities.filter(function (cap) {
      if (kind && cap.kind !== kind) return false;
      if (framework) {
        if (!cap.frameworks || cap.frameworks.indexOf(framework) === -1) return false;
      }
      if (query) {
        var searchText = (cap.name + ' ' + (cap.owner || '') + ' ' + (cap.description || '')).toLowerCase();
        if (searchText.indexOf(query) === -1) return false;
      }
      return true;
    });

    renderCards();
  }

  function renderCards() {
    var grid = els.cardGrid;
    var count = state.filtered.length;
    els.resultCount.textContent = count;

    if (count === 0) {
      grid.innerHTML =
        '<div class="empty-state">' +
        '<div class="empty-state-icon">\uD83D\uDD0D</div>' +
        '<div class="empty-state-text">No capabilities found</div>' +
        '<div style="font-size:12px;color:var(--text-muted)">Try adjusting your search or filters</div>' +
        '</div>';
      return;
    }

    var html = '';
    state.filtered.forEach(function (cap) {
      var kindClass = cap.kind || 'skill';
      var owner = cap.owner || '';
      var displayName = owner
        ? owner + '/' + cap.name
        : cap.name;
      var frameworksHtml = '';
      if (cap.frameworks && cap.frameworks.length) {
        frameworksHtml = cap.frameworks.map(function (f) {
          return '<span class="card-tag">' + escapeHtml(f) + '</span>';
        }).join('');
      }
      var desc = cap.description || 'No description provided.';

      html +=
        '<div class="card" data-name="' + escapeHtml(cap.name) + '" data-owner="' + escapeHtml(owner) + '">' +
        '<div class="card-header">' +
        '<div>' +
        '<div class="card-name">' + escapeHtml(displayName) + '</div>' +
        '<div class="card-owner">v' + escapeHtml(cap.version) + '</div>' +
        '</div>' +
        '<span class="card-kind ' + kindClass + '">' + escapeHtml(kindClass) + '</span>' +
        '</div>' +
        '<div class="card-desc">' + escapeHtml(desc) + '</div>' +
        '<div class="card-meta">' +
        '<span class="card-version">' + escapeHtml(cap.version) + '</span>' +
        frameworksHtml +
        '</div>' +
        '</div>';
    });

    grid.innerHTML = html;

    qsa('.card').forEach(function (card) {
      card.addEventListener('click', function () {
        var name = card.dataset.name;
        var owner = card.dataset.owner;
        var capId = owner ? owner + '/' + name : name;
        showDetail(capId);
      });
    });
  }

  function showDetail(capId) {
    var url = API_BASE + '/capabilities/' + encodeURIComponent(capId);

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (cap) {
        renderModal(cap);
        els.modal.classList.add('open');
        document.body.style.overflow = 'hidden';
      })
      .catch(function (err) {
        els.modalBody.innerHTML = '<p style="color:var(--red)">Error: ' + escapeHtml(err.message) + '</p>';
        els.modal.classList.add('open');
        document.body.style.overflow = 'hidden';
      });
  }

  function renderModal(cap) {
    var kindClass = cap.kind || 'skill';
    var owner = cap.owner || '';
    var capId = owner ? owner + '/' + cap.name : cap.name;
    var installCmd = 'cap install ' + capId;
    var desc = cap.description || 'No description provided.';

    var frameworksHtml = '';
    if (cap.frameworks && cap.frameworks.length) {
      frameworksHtml = cap.frameworks.map(function (f) {
        return '<span class="card-tag">' + escapeHtml(f) + '</span>';
      }).join('');
    }

    var depsHtml = '';
    if (cap.dependencies && Object.keys(cap.dependencies).length) {
      depsHtml = Object.keys(cap.dependencies).map(function (dep) {
        var ver = cap.dependencies[dep];
        return '<li class="dep-item">' + escapeHtml(dep) + (ver ? ' <span style="color:var(--text-muted)">' + escapeHtml(ver) + '</span>' : '') + '</li>';
      }).join('');
      depsHtml = '<ul class="dep-list">' + depsHtml + '</ul>';
    } else {
      depsHtml = '<span style="color:var(--text-muted);font-size:13px">None</span>';
    }

    els.modalBody.innerHTML =
      '<div class="modal-header">' +
      '<div class="modal-name">' + escapeHtml(cap.name) + '</div>' +
      '<div class="modal-id">' + escapeHtml(capId) + '</div>' +
      '<span class="modal-kind ' + kindClass + '">' + escapeHtml(kindClass) + '</span>' +
      '</div>' +

      '<div class="modal-section">' +
      '<div class="modal-section-title">Description</div>' +
      '<div class="modal-desc">' + escapeHtml(desc) + '</div>' +
      '</div>' +

      '<div class="modal-section">' +
      '<div class="modal-section-title">Details</div>' +
      '<div class="modal-grid">' +
      '<div class="modal-field"><div class="modal-field-label">Version</div><div class="modal-field-value">' + escapeHtml(cap.version) + '</div></div>' +
      '<div class="modal-field"><div class="modal-field-label">Owner</div><div class="modal-field-value">' + escapeHtml(owner || '\u2014') + '</div></div>' +
      (cap.fingerprint ? '<div class="modal-field" style="grid-column:1/-1"><div class="modal-field-label">Fingerprint</div><div class="modal-field-value" style="font-size:11px">' + escapeHtml(cap.fingerprint) + '</div></div>' : '') +
      '</div>' +
      '</div>' +

      (frameworksHtml ? '<div class="modal-section"><div class="modal-section-title">Frameworks</div><div style="display:flex;gap:6px;flex-wrap:wrap">' + frameworksHtml + '</div></div>' : '') +

      '<div class="modal-section">' +
      '<div class="modal-section-title">Dependencies</div>' +
      depsHtml +
      '</div>' +

      '<div class="modal-section">' +
      '<div class="modal-section-title">Install</div>' +
      '<div class="install-box">' +
      '<code class="install-command" id="install-command">$ ' + escapeHtml(installCmd) + '</code>' +
      '<button class="install-copy" id="install-copy-btn">Copy</button>' +
      '</div>' +
      '</div>';

    var copyBtn = document.getElementById('install-copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        navigator.clipboard.writeText(installCmd).then(function () {
          copyBtn.textContent = 'Copied!';
          copyBtn.classList.add('copied');
          setTimeout(function () {
            copyBtn.textContent = 'Copy';
            copyBtn.classList.remove('copied');
          }, 2000);
        });
      });
    }
  }

  function closeModal() {
    els.modal.classList.remove('open');
    document.body.style.overflow = '';
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

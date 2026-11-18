/* Caos BioGuard · Web Admin 主题切换 */
(function () {
    const KEY = 'caos-theme';
    const THEMES = [
        { key: 'obsidian', label: '深空青 · Obsidian' },
        { key: 'aurora', label: '极光紫 · Aurora' },
        { key: 'ember', label: '熔金橙 · Ember' },
        { key: 'daybreak', label: '晨雾白 · Daybreak' }
    ];

    function apply(key) {
        const valid = THEMES.some(t => t.key === key) ? key : 'obsidian';
        document.documentElement.setAttribute('data-theme', valid);
        try { localStorage.setItem(KEY, valid); } catch (e) { /* ignore */ }
        const sel = document.getElementById('themeSelect');
        if (sel && sel.value !== valid) sel.value = valid;
        window.dispatchEvent(new CustomEvent('caos:theme', { detail: valid }));
    }

    function current() {
        try {
            const stored = localStorage.getItem(KEY);
            if (stored) return stored;
        } catch (e) { /* ignore */ }
        return document.documentElement.getAttribute('data-theme') || 'obsidian';
    }

    window.CaosTheme = { apply, current, themes: THEMES };

    document.addEventListener('DOMContentLoaded', function () {
        const sel = document.getElementById('themeSelect');
        if (sel) {
            sel.innerHTML = THEMES.map(t =>
                '<option value="' + t.key + '">' + t.label + '</option>'
            ).join('');
            sel.value = current();
            sel.addEventListener('change', function () { apply(sel.value); });
        }
        apply(current());
    });
})();

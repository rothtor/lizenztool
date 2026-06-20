// ── i18n (Internationalization) with Security ────────────────────────────────

// Whitelist of allowed languages (SECURITY: prevent directory traversal)
const ALLOWED_LANGUAGES = ['en', 'de'];
const DEFAULT_LANGUAGE = 'en';

let i18nData = {};
let currentLanguage = DEFAULT_LANGUAGE;

/**
 * Safe language getter with whitelist validation.
 * Prevents directory traversal and injection attacks.
 */
function getSafeLanguage(lang) {
  if (!lang || typeof lang !== 'string') return DEFAULT_LANGUAGE;
  const normalized = lang.toLowerCase().trim();
  if (ALLOWED_LANGUAGES.includes(normalized)) {
    return normalized;
  }
  return DEFAULT_LANGUAGE;
}

/**
 * Initialize i18n system
 */
async function initI18n() {
  // Get language from localStorage or browser default
  let lang = localStorage.getItem('language') || navigator.language.split('-')[0];
  currentLanguage = getSafeLanguage(lang);

  // Load language file
  try {
    const response = await fetch(`/static/locales/${currentLanguage}.json`);
    if (!response.ok) throw new Error('Language file not found');
    i18nData = await response.json();
  } catch (err) {
    console.error('Failed to load language:', currentLanguage, err);
    // Fallback to default
    currentLanguage = DEFAULT_LANGUAGE;
    const response = await fetch(`/static/locales/${DEFAULT_LANGUAGE}.json`);
    i18nData = await response.json();
  }

  // Set HTML lang attribute
  document.documentElement.lang = currentLanguage;

  // Apply language to UI
  applyTranslations();

  // Setup language switcher
  setupLanguageSwitcher();
}

/**
 * Translate a key with dot notation (e.g., "ui.select_file")
 */
function t(key, fallback = key) {
  const parts = key.split('.');
  let value = i18nData;

  for (const part of parts) {
    if (value && typeof value === 'object' && part in value) {
      value = value[part];
    } else {
      return fallback;
    }
  }

  return typeof value === 'string' ? value : fallback;
}

/**
 * Apply translations to all elements with data-i18n attribute
 */
function applyTranslations() {
  // Handle regular text content
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    const text = t(key);

    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      if (el.hasAttribute('placeholder')) {
        el.placeholder = text;
      } else {
        el.value = text;
      }
    } else {
      el.textContent = text;
    }
  });

  // Handle placeholder translations
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.placeholder = t(key);
  });

  // Update language switcher button text
  updateLanguageSwitcherLabel();
}

/**
 * Switch to a different language
 */
async function switchLanguage(lang) {
  const newLang = getSafeLanguage(lang);
  if (newLang === currentLanguage) return;

  try {
    const response = await fetch(`/static/locales/${newLang}.json`);
    if (!response.ok) throw new Error('Language file not found');
    i18nData = await response.json();
    currentLanguage = newLang;

    // Save to localStorage
    localStorage.setItem('language', newLang);

    // Update UI
    document.documentElement.lang = currentLanguage;
    applyTranslations();

    // Update dynamic content like CC_DATA
    if (window.syncCcInfo) window.syncCcInfo();
  } catch (err) {
    console.error('Failed to switch language:', err);
  }
}

/**
 * Setup language switcher in header
 */
function setupLanguageSwitcher() {
  const header = document.querySelector('header');
  if (!header) return;

  const switcher = document.createElement('div');
  switcher.className = 'lang-switcher';
  switcher.innerHTML = `
    <button type="button" class="lang-btn" data-lang="en" title="English">EN</button>
    <button type="button" class="lang-btn" data-lang="de" title="Deutsch">DE</button>
    <button type="button" class="reset-btn" title="Reset" id="reset-btn">↻</button>
  `;

  // Mark active language
  const activeBtn = switcher.querySelector(`[data-lang="${currentLanguage}"]`);
  if (activeBtn) activeBtn.classList.add('active');

  // Add click handlers for language buttons
  switcher.querySelectorAll('.lang-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const lang = btn.getAttribute('data-lang');
      switchLanguage(lang);

      // Update active state
      switcher.querySelectorAll('.lang-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  // Add reset handler
  const resetBtn = switcher.querySelector('#reset-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      location.reload();
    });
  }

  header.appendChild(switcher);
}

/**
 * Update language switcher button label
 */
function updateLanguageSwitcherLabel() {
  // This is kept for potential future use
  // Currently, button labels are fixed (EN/DE)
}

/**
 * Get localized CC_DATA structure for current language
 */
function getCC_DATA() {
  const cc = i18nData.cc_info || {};
  return {
    "CC BY 4.0":      { erlaubt: cc.cc_by?.allowed || "Share & modify, commercial allowed", bedingung: cc.cc_by?.requirement || "Attribution required", url: "https://creativecommons.org/licenses/by/4.0/deed.de" },
    "CC BY-SA 4.0":   { erlaubt: cc.cc_by_sa?.allowed || "Share & modify, commercial allowed", bedingung: cc.cc_by_sa?.requirement || "Attribution + share-alike", url: "https://creativecommons.org/licenses/by-sa/4.0/deed.de" },
    "CC BY-NC 4.0":   { erlaubt: cc.cc_by_nc?.allowed || "Share & modify", bedingung: cc.cc_by_nc?.requirement || "Attribution + non-commercial only", url: "https://creativecommons.org/licenses/by-nc/4.0/deed.de" },
    "CC BY-NC-SA 4.0":{ erlaubt: cc.cc_by_nc_sa?.allowed || "Share & modify", bedingung: cc.cc_by_nc_sa?.requirement || "Attribution + non-commercial + share-alike", url: "https://creativecommons.org/licenses/by-nc-sa/4.0/deed.de" },
    "CC BY-ND 4.0":   { erlaubt: cc.cc_by_nd?.allowed || "Share, commercial allowed", bedingung: cc.cc_by_nd?.requirement || "Attribution + no derivatives", url: "https://creativecommons.org/licenses/by-nd/4.0/deed.de" },
    "CC BY-NC-ND 4.0":{ erlaubt: cc.cc_by_nc_nd?.allowed || "Share only", bedingung: cc.cc_by_nc_nd?.requirement || "Attribution + non-commercial + no derivatives", url: "https://creativecommons.org/licenses/by-nc-nd/4.0/deed.de" },
    "CC0 1.0 (Public Domain)": { erlaubt: cc.cc0?.allowed || "Everything – no restrictions", bedingung: cc.cc0?.requirement || "No conditions (Public Domain)", url: "https://creativecommons.org/publicdomain/zero/1.0/deed.de" },
    "All Rights Reserved":     { erlaubt: cc.all_rights?.allowed || "No free use", bedingung: cc.all_rights?.requirement || "All rights reserved", url: null },
  };
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initI18n);
} else {
  initI18n();
}

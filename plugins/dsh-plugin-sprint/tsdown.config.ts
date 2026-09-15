/**
 * Сборка браузерного бандла карточки. Рецепт повторяет closure-factory харнесса
 * (`harness-ui/packages/client/tsdown.client.ts`, `clientConfig`) для плагина вне
 * его дерева: бандл зовёт `window.__ModuleLoader__.load({id, factory})`, а внешние
 * модули резолвит через переданный `require` — таблицу модулей оболочки.
 *
 * Узловая половина (`lib/index.js`) выпускается `tsc`, не отсюда, поэтому `clean`
 * выключен: иначе этот бандл затирал бы её.
 *
 * Структура взята у прецедентов (`dsh-plugin-bft`, `dsh-communication-plugin`) —
 * тот же харнесс, та же версия API плагинов.
 */
import { defineConfig } from 'tsdown'

/**
 * Внешние модули, на которые отвечает таблица оболочки: импортируются обычным
 * образом и остаются в бандле вызовами `require`. Всё прочее обязано влиться.
 *
 * Источник — `PLATFORM_MODULES` браузерной платформы харнесса; список сверен по
 * прецеденту `dsh-plugin-bft/tsdown.config.ts`, который, в свою очередь, сверял
 * его с живым харнессом.
 */
const CLIENT_EXTERNALS: readonly string[] = [
  'react',
  'react/jsx-runtime',
  'react-dom',
  'react-dom/client',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-store',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-ui-primitives',
]

/** Слои-контракты, которые браузерному бандлу можно влить: у них нет разделяемой идентичности. */
const INLINE_SAFE = /^(?:@deepseek-ai\/dsh-(?:file-reference|session|llm|tools|brand|deque|typert-protocol|util-crypto|util-values|util-workspace-path)(?:\/|$)|@deepseek-ai\/dsh-token-meter\/client$|@deepseek-ai\/dsh-agent-presets\/display$)/

/** Вендорные библиотеки фреймворка: обычные библиотеки, которые бандл вливает. */
const VENDORED_LIBRARY = /^@deepseek-ai\/(cosmokit|schemastery)(\/|$)/

/** Сгенерированный вклад дескрипторов без разделяемой идентичности. */
const GENERATED_REMOTE = /^@deepseek-ai\/dsh-[a-z0-9]+(?:-[a-z0-9]+)*\/remote$/

export default defineConfig({
  name: 'dsh-plugin-sprint/client',
  entry: { client: 'src/client/index.tsx' },
  // Общий с tsc каталог артефактов; entryFileNames закрепляет бандл за lib/client.js.
  outDir: 'lib',
  format: 'cjs',
  platform: 'browser',
  // Типы выпускает tsc (lib/client/index.d.ts); dts здесь завернул бы banner/footer в .d.cts.
  dts: false,
  sourcemap: true,
  clean: false,
  deps: {
    neverBundle: (specifier: string) => CLIENT_EXTERNALS.includes(specifier),
    // Чего нет в таблице модулей — обязано влиться: `require`, на который таблица
    // не отвечает, это гарантированный бросок в рантайме.
    alwaysBundle: (specifier: string) => !CLIENT_EXTERNALS.includes(specifier),
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
    'import.meta.env.MODE': JSON.stringify('production'),
    'import.meta.env': JSON.stringify({ MODE: 'production' }),
  },
  plugins: [{
    // Сторож чистоты бандла: записи таблицы модулей остаются внешними,
    // inline-safe слои и вендорные библиотеки вливаются, любой другой
    // value-импорт пакета харнесса — ошибка сборки.
    name: 'dsh-client-bundle-purity',
    resolveId(source: string) {
      if (!source.startsWith('@deepseek-ai/')) return null
      if (CLIENT_EXTERNALS.includes(source)) return null
      if (VENDORED_LIBRARY.test(source)) return null
      if (INLINE_SAFE.test(source) || GENERATED_REMOTE.test(source)) return null
      throw new Error(
        `сторож чистоты: пакет "${source}" не входит ни в CLIENT_EXTERNALS, ни в inline-safe wire-слои, `
        + 'ни в сгенерированные /remote-вклады — value-импорты пакетов харнесса запрещены; '
        + 'сотрудничество идёт через службы cordis (type-only импорты стираются транспайлером)',
      )
    },
  }],
  outputOptions: {
    entryFileNames: 'client.js',
    banner: 'window.__ModuleLoader__.load({ id: "dsh-plugin-sprint", factory: (require) => {',
    footer: 'return module.exports; } });',
    intro: 'var module = { exports: {} }; var exports = module.exports;',
  },
})

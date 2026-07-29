.
├── agents
│   ├── agent-architecture.jsx
│   ├── agents-groups
│   │   ├── _meta
│   │   │   ├── groups.index.json
│   │   │   ├── meta-orchestrator.agent.md
│   │   │   └── policies
│   │   ├── coremu
│   │   │   ├── docs
│   │   │   ├── index.json
│   │   │   ├── knowledge
│   │   │   └── policies
│   │   ├── government
│   │   │   ├── agents
│   │   │   ├── index.json
│   │   │   ├── knowledge
│   │   │   └── policies
│   │   ├── legal
│   │   │   ├── agents
│   │   │   ├── index.json
│   │   │   ├── knowledge
│   │   │   └── policies
│   │   └── olivia
│   │       ├── agents
│   │       ├── index.json
│   │       └── knowledge
│   ├── CHANGELOG.md
│   ├── deploy
│   │   ├── agent-architecture.service
│   │   └── agent-skill-service.service
│   ├── docs
│   │   ├── DEVELOPMENT_PLAN.md
│   │   ├── MCP_BOOTSTRAP_STANDARD.md
│   │   └── PROJECT_OVERVIEW.md
│   ├── examples
│   │   ├── fixtures
│   │   │   ├── example-payloads.json
│   │   │   ├── README.md
│   │   │   ├── sample.csv
│   │   │   ├── sample.json
│   │   │   ├── sample.pdf
│   │   │   └── sample.txt
│   │   └── uploads
│   ├── generated
│   │   ├── agents
│   │   │   ├── api-explorer.agent.md
│   │   │   ├── coremu-coordinator.agent.md
│   │   │   ├── coremu-darik.agent.md
│   │   │   ├── coremu-ester.agent.md
│   │   │   ├── coremu-giselle.agent.md
│   │   │   ├── coremu-jessica.agent.md
│   │   │   ├── coremu-kassio.agent.md
│   │   │   ├── coremu-laura.agent.md
│   │   │   ├── coremu-magdi.agent.md
│   │   │   ├── coremu-maira.agent.md
│   │   │   ├── coremu-maria-eduarda.agent.md
│   │   │   ├── coremu-orchestrator.agent.md
│   │   │   ├── coremu-patricia.agent.md
│   │   │   ├── discovery-intelligence.agent.md
│   │   │   ├── listening-operations.agent.md
│   │   │   ├── mcp-tool-test-refiner.agent.md
│   │   │   ├── mcp-tools-concierge.agent.md
│   │   │   ├── memory-graph.agent.md
│   │   │   ├── orchestrator-control-plane.agent.md
│   │   │   ├── qdrant-manager.agent.md
│   │   │   ├── shaders-proactive.agent.md
│   │   │   └── studio-ui.agent.md
│   │   ├── build-legal-pack.py
│   │   ├── build-mcp-catalog.mjs
│   │   ├── build-pack.mjs
│   │   ├── bundles
│   │   │   ├── apiexplorer.bundle.import.json
│   │   │   ├── coremu-coordinator.bundle.import.json
│   │   │   ├── coremu-darik.bundle.import.json
│   │   │   ├── coremu-ester.bundle.import.json
│   │   │   ├── coremu-giselle.bundle.import.json
│   │   │   ├── coremu-jessica.bundle.import.json
│   │   │   ├── coremu-kassio.bundle.import.json
│   │   │   ├── coremu-laura.bundle.import.json
│   │   │   ├── coremu-magdi.bundle.import.json
│   │   │   ├── coremu-maira.bundle.import.json
│   │   │   ├── coremu-maria-eduarda.bundle.import.json
│   │   │   ├── coremu-orchestrator.bundle.import.json
│   │   │   ├── coremu-patricia.bundle.import.json
│   │   │   ├── discovery.bundle.import.json
│   │   │   ├── ibsco-cfo.bundle.import.json
│   │   │   ├── ibsco-pcp.bundle.import.json
│   │   │   ├── index.json
│   │   │   ├── listening.bundle.import.json
│   │   │   ├── memory.bundle.import.json
│   │   │   ├── orchestrator.bundle.import.json
│   │   │   ├── qdrant.bundle.import.json
│   │   │   ├── shaders.bundle.import.json
│   │   │   └── studio.bundle.import.json
│   │   ├── check-schema-versions.mjs
│   │   ├── ci-gate.sh
│   │   ├── government
│   │   │   ├── bundles
│   │   │   └── government-agents.index.json
│   │   ├── import-all-bundles.mjs
│   │   ├── legal
│   │   │   ├── agents
│   │   │   ├── bundles
│   │   │   ├── import-legal-bundles.mjs
│   │   │   ├── legal-agents.index.json
│   │   │   ├── policies
│   │   │   └── README.md
│   │   ├── mcp
│   │   │   ├── index.json
│   │   │   ├── README.md
│   │   │   ├── servers.summary.json
│   │   │   └── tools.catalog.json
│   │   ├── memory-group-assignments.json
│   │   ├── policies
│   │   │   ├── handoff-routes.json
│   │   │   ├── orchestrator-policy.yaml
│   │   │   └── tool-permissions.by-agent.json
│   │   ├── README.md
│   │   ├── schemas
│   │   │   ├── group-manifest.schema.json
│   │   │   ├── handoff-payload.schema.json
│   │   │   ├── knowledge-manifest.schema.json
│   │   │   ├── mcp-servers-registry.schema.json
│   │   │   └── tool-permissions.schema.json
│   │   ├── tests
│   │   │   └── test_meta_route.py
│   │   └── validate-pack.mjs
│   ├── index.html
│   ├── proposals
│   ├── README.md
│   ├── serve.py
│   ├── service
│   │   ├── dist
│   │   │   ├── core
│   │   │   ├── index.d.ts
│   │   │   ├── index.js
│   │   │   └── skills
│   │   ├── docs
│   │   │   ├── app.js
│   │   │   ├── index.html
│   │   │   └── styles.css
│   │   ├── examples
│   │   │   └── basic-usage.ts
│   │   ├── integration
│   │   │   ├── skill-collection.manifest.json
│   │   │   ├── skill-delta-report.json
│   │   │   └── skill-delta-report.md
│   │   ├── message.json
│   │   ├── node_modules
│   │   │   ├── @anthropic-ai
│   │   │   ├── @babel
│   │   │   ├── @bcoe
│   │   │   ├── @eslint
│   │   │   ├── @eslint-community
│   │   │   ├── @humanwhocodes
│   │   │   ├── @istanbuljs
│   │   │   ├── @jest
│   │   │   ├── @jridgewell
│   │   │   ├── @nodelib
│   │   │   ├── @sinclair
│   │   │   ├── @sinonjs
│   │   │   ├── @types
│   │   │   ├── @typescript-eslint
│   │   │   ├── @ungap
│   │   │   ├── abort-controller
│   │   │   ├── acorn
│   │   │   ├── acorn-jsx
│   │   │   ├── agentkeepalive
│   │   │   ├── ajv
│   │   │   ├── ansi-escapes
│   │   │   ├── ansi-regex
│   │   │   ├── ansi-styles
│   │   │   ├── anymatch
│   │   │   ├── argparse
│   │   │   ├── array-union
│   │   │   ├── asynckit
│   │   │   ├── babel-jest
│   │   │   ├── babel-plugin-istanbul
│   │   │   ├── babel-plugin-jest-hoist
│   │   │   ├── babel-preset-current-node-syntax
│   │   │   ├── babel-preset-jest
│   │   │   ├── balanced-match
│   │   │   ├── baseline-browser-mapping
│   │   │   ├── brace-expansion
│   │   │   ├── braces
│   │   │   ├── browserslist
│   │   │   ├── bs-logger
│   │   │   ├── bser
│   │   │   ├── buffer-from
│   │   │   ├── call-bind-apply-helpers
│   │   │   ├── callsites
│   │   │   ├── camelcase
│   │   │   ├── caniuse-lite
│   │   │   ├── chalk
│   │   │   ├── char-regex
│   │   │   ├── ci-info
│   │   │   ├── cjs-module-lexer
│   │   │   ├── cliui
│   │   │   ├── co
│   │   │   ├── collect-v8-coverage
│   │   │   ├── color-convert
│   │   │   ├── color-name
│   │   │   ├── combined-stream
│   │   │   ├── concat-map
│   │   │   ├── convert-source-map
│   │   │   ├── create-jest
│   │   │   ├── cross-spawn
│   │   │   ├── debug
│   │   │   ├── dedent
│   │   │   ├── deep-is
│   │   │   ├── deepmerge
│   │   │   ├── delayed-stream
│   │   │   ├── detect-newline
│   │   │   ├── diff-sequences
│   │   │   ├── dir-glob
│   │   │   ├── doctrine
│   │   │   ├── dunder-proto
│   │   │   ├── electron-to-chromium
│   │   │   ├── emittery
│   │   │   ├── emoji-regex
│   │   │   ├── error-ex
│   │   │   ├── es-define-property
│   │   │   ├── es-errors
│   │   │   ├── es-object-atoms
│   │   │   ├── es-set-tostringtag
│   │   │   ├── escalade
│   │   │   ├── escape-string-regexp
│   │   │   ├── eslint
│   │   │   ├── eslint-scope
│   │   │   ├── eslint-visitor-keys
│   │   │   ├── espree
│   │   │   ├── esprima
│   │   │   ├── esquery
│   │   │   ├── esrecurse
│   │   │   ├── estraverse
│   │   │   ├── esutils
│   │   │   ├── event-target-shim
│   │   │   ├── execa
│   │   │   ├── exit
│   │   │   ├── expect
│   │   │   ├── fast-deep-equal
│   │   │   ├── fast-glob
│   │   │   ├── fast-json-stable-stringify
│   │   │   ├── fast-levenshtein
│   │   │   ├── fastq
│   │   │   ├── fb-watchman
│   │   │   ├── file-entry-cache
│   │   │   ├── fill-range
│   │   │   ├── find-up
│   │   │   ├── flat-cache
│   │   │   ├── flatted
│   │   │   ├── form-data
│   │   │   ├── form-data-encoder
│   │   │   ├── formdata-node
│   │   │   ├── fs.realpath
│   │   │   ├── function-bind
│   │   │   ├── gensync
│   │   │   ├── get-caller-file
│   │   │   ├── get-intrinsic
│   │   │   ├── get-package-type
│   │   │   ├── get-proto
│   │   │   ├── get-stream
│   │   │   ├── glob
│   │   │   ├── glob-parent
│   │   │   ├── globals
│   │   │   ├── globby
│   │   │   ├── gopd
│   │   │   ├── graceful-fs
│   │   │   ├── graphemer
│   │   │   ├── handlebars
│   │   │   ├── has-flag
│   │   │   ├── has-symbols
│   │   │   ├── has-tostringtag
│   │   │   ├── hasown
│   │   │   ├── html-escaper
│   │   │   ├── human-signals
│   │   │   ├── humanize-ms
│   │   │   ├── ignore
│   │   │   ├── import-fresh
│   │   │   ├── import-local
│   │   │   ├── imurmurhash
│   │   │   ├── inflight
│   │   │   ├── inherits
│   │   │   ├── is-arrayish
│   │   │   ├── is-core-module
│   │   │   ├── is-extglob
│   │   │   ├── is-fullwidth-code-point
│   │   │   ├── is-generator-fn
│   │   │   ├── is-glob
│   │   │   ├── is-number
│   │   │   ├── is-path-inside
│   │   │   ├── is-stream
│   │   │   ├── isexe
│   │   │   ├── istanbul-lib-coverage
│   │   │   ├── istanbul-lib-instrument
│   │   │   ├── istanbul-lib-report
│   │   │   ├── istanbul-lib-source-maps
│   │   │   ├── istanbul-reports
│   │   │   ├── jest
│   │   │   ├── jest-changed-files
│   │   │   ├── jest-circus
│   │   │   ├── jest-cli
│   │   │   ├── jest-config
│   │   │   ├── jest-diff
│   │   │   ├── jest-docblock
│   │   │   ├── jest-each
│   │   │   ├── jest-environment-node
│   │   │   ├── jest-get-type
│   │   │   ├── jest-haste-map
│   │   │   ├── jest-leak-detector
│   │   │   ├── jest-matcher-utils
│   │   │   ├── jest-message-util
│   │   │   ├── jest-mock
│   │   │   ├── jest-pnp-resolver
│   │   │   ├── jest-regex-util
│   │   │   ├── jest-resolve
│   │   │   ├── jest-resolve-dependencies
│   │   │   ├── jest-runner
│   │   │   ├── jest-runtime
│   │   │   ├── jest-snapshot
│   │   │   ├── jest-util
│   │   │   ├── jest-validate
│   │   │   ├── jest-watcher
│   │   │   ├── jest-worker
│   │   │   ├── js-tokens
│   │   │   ├── js-yaml
│   │   │   ├── jsesc
│   │   │   ├── json-buffer
│   │   │   ├── json-parse-even-better-errors
│   │   │   ├── json-schema-traverse
│   │   │   ├── json-stable-stringify-without-jsonify
│   │   │   ├── json5
│   │   │   ├── keyv
│   │   │   ├── kleur
│   │   │   ├── leven
│   │   │   ├── levn
│   │   │   ├── lines-and-columns
│   │   │   ├── locate-path
│   │   │   ├── lodash-es
│   │   │   ├── lodash.memoize
│   │   │   ├── lodash.merge
│   │   │   ├── lru-cache
│   │   │   ├── make-dir
│   │   │   ├── make-error
│   │   │   ├── makeerror
│   │   │   ├── math-intrinsics
│   │   │   ├── merge-stream
│   │   │   ├── merge2
│   │   │   ├── micromatch
│   │   │   ├── mime-db
│   │   │   ├── mime-types
│   │   │   ├── mimic-fn
│   │   │   ├── minimatch
│   │   │   ├── minimist
│   │   │   ├── ms
│   │   │   ├── natural-compare
│   │   │   ├── neo-async
│   │   │   ├── node-domexception
│   │   │   ├── node-fetch
│   │   │   ├── node-int64
│   │   │   ├── node-releases
│   │   │   ├── normalize-path
│   │   │   ├── npm-run-path
│   │   │   ├── once
│   │   │   ├── onetime
│   │   │   ├── optionator
│   │   │   ├── p-limit
│   │   │   ├── p-locate
│   │   │   ├── p-try
│   │   │   ├── parent-module
│   │   │   ├── parse-json
│   │   │   ├── path-exists
│   │   │   ├── path-is-absolute
│   │   │   ├── path-key
│   │   │   ├── path-parse
│   │   │   ├── path-type
│   │   │   ├── picocolors
│   │   │   ├── picomatch
│   │   │   ├── pirates
│   │   │   ├── pkg-dir
│   │   │   ├── prelude-ls
│   │   │   ├── prettier
│   │   │   ├── pretty-format
│   │   │   ├── prompts
│   │   │   ├── punycode
│   │   │   ├── pure-rand
│   │   │   ├── queue-microtask
│   │   │   ├── react-is
│   │   │   ├── require-directory
│   │   │   ├── resolve
│   │   │   ├── resolve-cwd
│   │   │   ├── resolve-from
│   │   │   ├── resolve.exports
│   │   │   ├── reusify
│   │   │   ├── rimraf
│   │   │   ├── run-parallel
│   │   │   ├── semver
│   │   │   ├── shebang-command
│   │   │   ├── shebang-regex
│   │   │   ├── signal-exit
│   │   │   ├── sisteransi
│   │   │   ├── slash
│   │   │   ├── source-map
│   │   │   ├── source-map-support
│   │   │   ├── sprintf-js
│   │   │   ├── stack-utils
│   │   │   ├── string-length
│   │   │   ├── string-width
│   │   │   ├── strip-ansi
│   │   │   ├── strip-bom
│   │   │   ├── strip-final-newline
│   │   │   ├── strip-json-comments
│   │   │   ├── supports-color
│   │   │   ├── supports-preserve-symlinks-flag
│   │   │   ├── test-exclude
│   │   │   ├── text-table
│   │   │   ├── tmpl
│   │   │   ├── to-regex-range
│   │   │   ├── tr46
│   │   │   ├── ts-api-utils
│   │   │   ├── ts-jest
│   │   │   ├── type-check
│   │   │   ├── type-detect
│   │   │   ├── type-fest
│   │   │   ├── typescript
│   │   │   ├── uglify-js
│   │   │   ├── undici-types
│   │   │   ├── update-browserslist-db
│   │   │   ├── uri-js
│   │   │   ├── v8-to-istanbul
│   │   │   ├── walker
│   │   │   ├── web-streams-polyfill
│   │   │   ├── webidl-conversions
│   │   │   ├── whatwg-url
│   │   │   ├── which
│   │   │   ├── word-wrap
│   │   │   ├── wordwrap
│   │   │   ├── wrap-ansi
│   │   │   ├── wrappy
│   │   │   ├── write-file-atomic
│   │   │   ├── y18n
│   │   │   ├── yallist
│   │   │   ├── yargs
│   │   │   ├── yargs-parser
│   │   │   ├── yocto-queue
│   │   │   └── zod
│   │   ├── package-lock.json
│   │   ├── package.json
│   │   ├── README.md
│   │   ├── scripts
│   │   │   ├── extract-skills.js
│   │   │   ├── integrate-skill-collection.mjs
│   │   │   └── start-docs.mjs
│   │   ├── src
│   │   │   ├── core
│   │   │   ├── index.ts
│   │   │   └── skills
│   │   └── tsconfig.json
│   ├── start.sh
│   └── stop.sh
├── awareness
│   ├── mcp_bridge.py
│   ├── openclaude
│   │   ├── ANDROID_INSTALL.md
│   │   ├── bin
│   │   │   ├── import-specifier.mjs
│   │   │   ├── import-specifier.test.mjs
│   │   │   └── openclaude
│   │   ├── bun.lock
│   │   ├── CHANGELOG.md
│   │   ├── CODE_OF_CONDUCT.md
│   │   ├── CONTRIBUTING.md
│   │   ├── dist
│   │   │   ├── cli.mjs
│   │   │   └── cli.mjs.map
│   │   ├── Dockerfile
│   │   ├── docs
│   │   │   ├── advanced-setup.md
│   │   │   ├── hook-chains.md
│   │   │   ├── litellm-setup.md
│   │   │   ├── non-technical-setup.md
│   │   │   ├── quick-start-mac-linux.md
│   │   │   └── quick-start-windows.md
│   │   ├── LICENSE
│   │   ├── node_modules
│   │   │   ├── @alcalzone
│   │   │   ├── @anthropic-ai
│   │   │   ├── @aws
│   │   │   ├── @aws-crypto
│   │   │   ├── @aws-sdk
│   │   │   ├── @babel
│   │   │   ├── @commander-js
│   │   │   ├── @esbuild
│   │   │   ├── @growthbook
│   │   │   ├── @grpc
│   │   │   ├── @hono
│   │   │   ├── @img
│   │   │   ├── @js-sdsl
│   │   │   ├── @mendable
│   │   │   ├── @mixmark-io
│   │   │   ├── @modelcontextprotocol
│   │   │   ├── @opentelemetry
│   │   │   ├── @pondwader
│   │   │   ├── @protobufjs
│   │   │   ├── @sec-ant
│   │   │   ├── @sindresorhus
│   │   │   ├── @smithy
│   │   │   ├── @types
│   │   │   ├── accepts
│   │   │   ├── agent-base
│   │   │   ├── ajv
│   │   │   ├── ajv-formats
│   │   │   ├── ansi-regex
│   │   │   ├── ansi-styles
│   │   │   ├── any-promise
│   │   │   ├── asynckit
│   │   │   ├── auto-bind
│   │   │   ├── axios
│   │   │   ├── base64-js
│   │   │   ├── bidi-js
│   │   │   ├── bignumber.js
│   │   │   ├── body-parser
│   │   │   ├── bowser
│   │   │   ├── buffer-equal-constant-time
│   │   │   ├── bun-types
│   │   │   ├── bytes
│   │   │   ├── call-bind-apply-helpers
│   │   │   ├── call-bound
│   │   │   ├── camelcase
│   │   │   ├── chalk
│   │   │   ├── chokidar
│   │   │   ├── cli-boxes
│   │   │   ├── cli-highlight
│   │   │   ├── cliui
│   │   │   ├── code-excerpt
│   │   │   ├── color-convert
│   │   │   ├── color-name
│   │   │   ├── combined-stream
│   │   │   ├── commander
│   │   │   ├── content-disposition
│   │   │   ├── content-type
│   │   │   ├── convert-to-spaces
│   │   │   ├── cookie
│   │   │   ├── cookie-signature
│   │   │   ├── cors
│   │   │   ├── cross-spawn
│   │   │   ├── cssfilter
│   │   │   ├── csstype
│   │   │   ├── debug
│   │   │   ├── decamelize
│   │   │   ├── delayed-stream
│   │   │   ├── depd
│   │   │   ├── detect-libc
│   │   │   ├── diff
│   │   │   ├── dijkstrajs
│   │   │   ├── dom-mutator
│   │   │   ├── duck-duck-scrape
│   │   │   ├── dunder-proto
│   │   │   ├── ecdsa-sig-formatter
│   │   │   ├── ee-first
│   │   │   ├── emoji-regex
│   │   │   ├── encodeurl
│   │   │   ├── env-paths
│   │   │   ├── es-define-property
│   │   │   ├── es-errors
│   │   │   ├── es-object-atoms
│   │   │   ├── es-set-tostringtag
│   │   │   ├── esbuild
│   │   │   ├── escalade
│   │   │   ├── escape-html
│   │   │   ├── escape-string-regexp
│   │   │   ├── etag
│   │   │   ├── eventsource
│   │   │   ├── eventsource-parser
│   │   │   ├── execa
│   │   │   ├── express
│   │   │   ├── express-rate-limit
│   │   │   ├── extend
│   │   │   ├── fast-deep-equal
│   │   │   ├── fast-uri
│   │   │   ├── fast-xml-builder
│   │   │   ├── fast-xml-parser
│   │   │   ├── fflate
│   │   │   ├── figures
│   │   │   ├── finalhandler
│   │   │   ├── find-up
│   │   │   ├── firecrawl
│   │   │   ├── follow-redirects
│   │   │   ├── form-data
│   │   │   ├── forwarded
│   │   │   ├── fresh
│   │   │   ├── fsevents
│   │   │   ├── function-bind
│   │   │   ├── fuse.js
│   │   │   ├── gaxios
│   │   │   ├── gcp-metadata
│   │   │   ├── get-caller-file
│   │   │   ├── get-east-asian-width
│   │   │   ├── get-intrinsic
│   │   │   ├── get-proto
│   │   │   ├── get-stream
│   │   │   ├── get-tsconfig
│   │   │   ├── google-auth-library
│   │   │   ├── google-logging-utils
│   │   │   ├── gopd
│   │   │   ├── graceful-fs
│   │   │   ├── gtoken
│   │   │   ├── has-flag
│   │   │   ├── has-symbols
│   │   │   ├── has-tostringtag
│   │   │   ├── hasown
│   │   │   ├── highlight.js
│   │   │   ├── hono
│   │   │   ├── html-entities
│   │   │   ├── http-errors
│   │   │   ├── https-proxy-agent
│   │   │   ├── human-signals
│   │   │   ├── iconv-lite
│   │   │   ├── ignore
│   │   │   ├── indent-string
│   │   │   ├── inherits
│   │   │   ├── ip-address
│   │   │   ├── ipaddr.js
│   │   │   ├── is-fullwidth-code-point
│   │   │   ├── is-plain-obj
│   │   │   ├── is-promise
│   │   │   ├── is-stream
│   │   │   ├── is-unicode-supported
│   │   │   ├── isexe
│   │   │   ├── jose
│   │   │   ├── json-bigint
│   │   │   ├── json-schema-to-ts
│   │   │   ├── json-schema-traverse
│   │   │   ├── json-schema-typed
│   │   │   ├── jsonc-parser
│   │   │   ├── jwa
│   │   │   ├── jws
│   │   │   ├── locate-path
│   │   │   ├── lodash-es
│   │   │   ├── lodash.camelcase
│   │   │   ├── lodash.debounce
│   │   │   ├── long
│   │   │   ├── lru-cache
│   │   │   ├── marked
│   │   │   ├── math-intrinsics
│   │   │   ├── media-typer
│   │   │   ├── merge-descriptors
│   │   │   ├── mime-db
│   │   │   ├── mime-types
│   │   │   ├── ms
│   │   │   ├── mz
│   │   │   ├── needle
│   │   │   ├── negotiator
│   │   │   ├── node-fetch
│   │   │   ├── npm-run-path
│   │   │   ├── object-assign
│   │   │   ├── object-inspect
│   │   │   ├── on-finished
│   │   │   ├── once
│   │   │   ├── p-limit
│   │   │   ├── p-locate
│   │   │   ├── p-map
│   │   │   ├── p-try
│   │   │   ├── parse-ms
│   │   │   ├── parse5
│   │   │   ├── parse5-htmlparser2-tree-adapter
│   │   │   ├── parseurl
│   │   │   ├── path-exists
│   │   │   ├── path-expression-matcher
│   │   │   ├── path-key
│   │   │   ├── path-to-regexp
│   │   │   ├── picomatch
│   │   │   ├── pkce-challenge
│   │   │   ├── pngjs
│   │   │   ├── pretty-ms
│   │   │   ├── proper-lockfile
│   │   │   ├── protobufjs
│   │   │   ├── proxy-addr
│   │   │   ├── proxy-from-env
│   │   │   ├── qrcode
│   │   │   ├── qs
│   │   │   ├── range-parser
│   │   │   ├── raw-body
│   │   │   ├── react
│   │   │   ├── react-compiler-runtime
│   │   │   ├── react-reconciler
│   │   │   ├── readdirp
│   │   │   ├── require-directory
│   │   │   ├── require-from-string
│   │   │   ├── require-main-filename
│   │   │   ├── resolve-pkg-maps
│   │   │   ├── retry
│   │   │   ├── router
│   │   │   ├── safe-buffer
│   │   │   ├── safer-buffer
│   │   │   ├── sax
│   │   │   ├── scheduler
│   │   │   ├── semver
│   │   │   ├── send
│   │   │   ├── serve-static
│   │   │   ├── set-blocking
│   │   │   ├── setprototypeof
│   │   │   ├── sharp
│   │   │   ├── shebang-command
│   │   │   ├── shebang-regex
│   │   │   ├── shell-quote
│   │   │   ├── side-channel
│   │   │   ├── side-channel-list
│   │   │   ├── side-channel-map
│   │   │   ├── side-channel-weakmap
│   │   │   ├── signal-exit
│   │   │   ├── stack-utils
│   │   │   ├── statuses
│   │   │   ├── string-width
│   │   │   ├── strip-ansi
│   │   │   ├── strip-final-newline
│   │   │   ├── strnum
│   │   │   ├── supports-color
│   │   │   ├── supports-hyperlinks
│   │   │   ├── thenify
│   │   │   ├── thenify-all
│   │   │   ├── toidentifier
│   │   │   ├── tr46
│   │   │   ├── tree-kill
│   │   │   ├── ts-algebra
│   │   │   ├── tslib
│   │   │   ├── tsx
│   │   │   ├── turndown
│   │   │   ├── type-fest
│   │   │   ├── type-is
│   │   │   ├── typescript
│   │   │   ├── typescript-event-target
│   │   │   ├── undici
│   │   │   ├── undici-types
│   │   │   ├── unicorn-magic
│   │   │   ├── unpipe
│   │   │   ├── usehooks-ts
│   │   │   ├── uuid
│   │   │   ├── vary
│   │   │   ├── vscode-jsonrpc
│   │   │   ├── vscode-languageserver-protocol
│   │   │   ├── vscode-languageserver-types
│   │   │   ├── webidl-conversions
│   │   │   ├── whatwg-url
│   │   │   ├── which
│   │   │   ├── which-module
│   │   │   ├── wrap-ansi
│   │   │   ├── wrappy
│   │   │   ├── ws
│   │   │   ├── xss
│   │   │   ├── y18n
│   │   │   ├── yaml
│   │   │   ├── yargs
│   │   │   ├── yargs-parser
│   │   │   ├── yoctocolors
│   │   │   ├── zod
│   │   │   └── zod-to-json-schema
│   │   ├── package.json
│   │   ├── PLAYBOOK.md
│   │   ├── python
│   │   │   ├── __init__.py
│   │   │   ├── atomic_chat_provider.py
│   │   │   ├── ollama_provider.py
│   │   │   ├── requirements.txt
│   │   │   ├── smart_router.py
│   │   │   └── tests
│   │   ├── README.md
│   │   ├── release-please-config.json
│   │   ├── scripts
│   │   │   ├── build.ts
│   │   │   ├── feature-flags-source-guard.test.ts
│   │   │   ├── grpc-cli.ts
│   │   │   ├── no-telemetry-growthbook-stub.test.ts
│   │   │   ├── no-telemetry-plugin.ts
│   │   │   ├── pr-intent-scan.test.ts
│   │   │   ├── pr-intent-scan.ts
│   │   │   ├── provider-bootstrap.ts
│   │   │   ├── provider-discovery.ts
│   │   │   ├── provider-launch.ts
│   │   │   ├── provider-recommend.ts
│   │   │   ├── render-coverage-heatmap.ts
│   │   │   ├── start-grpc.ts
│   │   │   ├── system-check.test.ts
│   │   │   ├── system-check.ts
│   │   │   ├── verify-no-phone-home.sh
│   │   │   └── verify-no-phone-home.ts
│   │   ├── SECURITY.md
│   │   ├── src
│   │   │   ├── __tests__
│   │   │   ├── assistant
│   │   │   ├── bootstrap
│   │   │   ├── bridge
│   │   │   ├── buddy
│   │   │   ├── cli
│   │   │   ├── commands
│   │   │   ├── commands.test.ts
│   │   │   ├── commands.ts
│   │   │   ├── components
│   │   │   ├── constants
│   │   │   ├── context
│   │   │   ├── context.ts
│   │   │   ├── coordinator
│   │   │   ├── cost-tracker.cacheIntegration.test.ts
│   │   │   ├── cost-tracker.ts
│   │   │   ├── costHook.ts
│   │   │   ├── dialogLaunchers.tsx
│   │   │   ├── entrypoints
│   │   │   ├── grpc
│   │   │   ├── history.ts
│   │   │   ├── hooks
│   │   │   ├── ink
│   │   │   ├── ink.ts
│   │   │   ├── interactiveHelpers.tsx
│   │   │   ├── keybindings
│   │   │   ├── main.tsx
│   │   │   ├── memdir
│   │   │   ├── migrations
│   │   │   ├── moreright
│   │   │   ├── native-ts
│   │   │   ├── outputStyles
│   │   │   ├── plugins
│   │   │   ├── projectOnboardingState.test.ts
│   │   │   ├── projectOnboardingState.ts
│   │   │   ├── projectOnboardingSteps.ts
│   │   │   ├── proto
│   │   │   ├── query
│   │   │   ├── query.ts
│   │   │   ├── QueryEngine.ts
│   │   │   ├── remote
│   │   │   ├── replLauncher.tsx
│   │   │   ├── schemas
│   │   │   ├── screens
│   │   │   ├── server
│   │   │   ├── services
│   │   │   ├── setup.ts
│   │   │   ├── skills
│   │   │   ├── state
│   │   │   ├── Task.ts
│   │   │   ├── tasks
│   │   │   ├── tasks.ts
│   │   │   ├── Tool.ts
│   │   │   ├── tools
│   │   │   ├── tools.ts
│   │   │   ├── types
│   │   │   ├── upstreamproxy
│   │   │   ├── utils
│   │   │   ├── vim
│   │   │   └── voice
│   │   ├── tsconfig.json
│   │   └── vscode-extension
│   │       └── openclaude-vscode
│   ├── README.md
│   ├── remote_bus_mcp.py
│   ├── requirements.txt
│   ├── serve.py
│   ├── start-all.sh
│   ├── static
│   │   └── css
│   │       └── awareness-brand.css
│   ├── stop-all.sh
│   ├── uploads
│   │   ├── agent_chats
│   │   ├── awareness_workspace.db
│   │   ├── projects
│   │   │   ├── _manifest.json
│   │   │   └── awareness-runtime-2026
│   │   └── reference_docx
│   └── workspace
│       ├── agent.html
│       ├── auth
│       │   ├── admin-activity.html
│       │   ├── admin-users.html
│       │   ├── change-password.html
│       │   ├── login.html
│       │   └── mode-select.html
│       ├── css
│       │   ├── agent-orchestration.css
│       │   ├── api-explorer.css
│       │   ├── architecture.css
│       │   ├── base.css
│       │   ├── browser-panel.css
│       │   ├── chat.css
│       │   ├── components.css
│       │   ├── descoberta.css
│       │   ├── docs.css
│       │   ├── endpoint-widget.css
│       │   ├── files.css
│       │   ├── history.css
│       │   ├── listening.css
│       │   ├── memory.css
│       │   ├── meshy-studio.css
│       │   ├── modals.css
│       │   ├── nav.css
│       │   ├── output-panel.css
│       │   ├── output-toggle-panel.css
│       │   ├── responsive.css
│       │   ├── shaders.css
│       │   ├── shared.css
│       │   ├── sidebar.css
│       │   ├── spaces.css
│       │   ├── studio.css
│       │   └── voice.css
│       ├── data
│       │   └── meshy-animation-catalog.json
│       ├── docs
│       │   └── design
│       ├── examples
│       │   ├── gbl-assets
│       │   └── svg-assets
│       ├── index.html
│       ├── js
│       │   ├── chat
│       │   ├── config.js
│       │   ├── core.js
│       │   ├── lib
│       │   ├── modals.js
│       │   ├── modules
│       │   ├── nav.js
│       │   ├── scene3d.js
│       │   ├── shaders.js
│       │   ├── sidebar
│       │   ├── spaces.js
│       │   ├── state.js
│       │   └── utils.js
│       ├── MIGRATION.md
│       ├── mobile.html
│       ├── OPENCLOUD_MULTI_AGENT_PLAYBOOK.md
│       ├── resident.html
│       ├── scenes
│       │   ├── arraial-dajuda-rave.scene.json
│       │   ├── arraial-dajuda.scene.json
│       │   ├── assets
│       │   ├── case-aeropuerto-stg5.scene.json
│       │   ├── castle-rock-walk.scene.json
│       │   ├── cozy-edinburgh-evening.scene.json
│       │   ├── custom_the_violation_windmill.scene.json
│       │   ├── enchanted-forest.scene.json
│       │   ├── happy-pups-backyard.scene.json
│       │   ├── ice-kingdom.scene.json
│       │   ├── jalapao.scene.json
│       │   ├── loch-golden-hour.scene.json
│       │   ├── manifest.json
│       │   ├── palmas-tocantins.scene.json
│       │   ├── rio-de-janeiro.scene.json
│       │   ├── snowy-playground-train.scene.json
│       │   ├── story-ch1-pups-discovery.scene.json
│       │   ├── story-ch2-forest-whispers.scene.json
│       │   ├── story-ch3-mountain-path.scene.json
│       │   ├── story-ch4-ice-gates.scene.json
│       │   ├── story-ch5-frozen-lake.scene.json
│       │   ├── story-ch6-magic-restored.scene.json
│       │   ├── truffle-outdoor.scene.json
│       │   ├── walled_garden_walk.scene.json
│       │   └── welcome.scene.json
│       └── shaderbench.html
├── back-ups
│   └── awareness
│       ├── 20260425T222905Z
│       │   └── uploads
│       ├── 20260425T223909Z
│       │   └── uploads
│       └── 20260425T230233Z
│           └── uploads
├── dev_tree.md
├── dev-tree.md
├── ops
│   ├── __pycache__
│   │   └── app.cpython-313.pyc
│   ├── ApiJson
│   ├── app.py
│   ├── BUSINESS_PLAN.md
│   ├── convert_report_to_json.py
│   ├── deploy
│   │   └── ops-dashboard.service
│   ├── network_traffic_store.json
│   ├── ops-dashboard.md
│   ├── ops-dashboard.service
│   ├── PROJECT_STATUS.md
│   ├── README.md
│   ├── requirements.txt
│   ├── start.sh
│   ├── static
│   │   └── css
│   │       └── awareness-brand.css
│   ├── stop.sh
│   └── templates
│       ├── dashboard.html
│       ├── login.html
│       └── observatory.html
└── services
    ├── discovery
    │   ├── case-server
    │   │   ├── _smoke_comprehend.js
    │   │   ├── auto_server_builder.js
    │   │   ├── node_modules
    │   │   ├── package-lock.json
    │   │   ├── package.json
    │   │   └── pipeline
    │   ├── deploy
    │   │   └── discovery.service
    │   ├── documents_scanned
    │   │   └── sessions
    │   ├── electron
    │   │   ├── main.js
    │   │   └── preload.js
    │   ├── endpoints_inventory.json
    │   ├── mcp
    │   │   ├── discovery_mcp_server.js
    │   │   ├── generate_readiness_artifacts.js
    │   │   ├── MCP_ARCHITECTURE.md
    │   │   └── mcp_readiness_report.md
    │   ├── node_modules
    │   │   ├── @develar
    │   │   ├── @electron
    │   │   ├── @hono
    │   │   ├── @isaacs
    │   │   ├── @malept
    │   │   ├── @modelcontextprotocol
    │   │   ├── @npmcli
    │   │   ├── @pkgjs
    │   │   ├── @sindresorhus
    │   │   ├── @szmarczak
    │   │   ├── @types
    │   │   ├── @xmldom
    │   │   ├── 7zip-bin
    │   │   ├── abbrev
    │   │   ├── accepts
    │   │   ├── agent-base
    │   │   ├── ajv
    │   │   ├── ajv-formats
    │   │   ├── ajv-keywords
    │   │   ├── ansi-regex
    │   │   ├── ansi-styles
    │   │   ├── app-builder-bin
    │   │   ├── app-builder-lib
    │   │   ├── append-field
    │   │   ├── argparse
    │   │   ├── array-flatten
    │   │   ├── assert-plus
    │   │   ├── astral-regex
    │   │   ├── async
    │   │   ├── async-exit-hook
    │   │   ├── asynckit
    │   │   ├── at-least-node
    │   │   ├── balanced-match
    │   │   ├── base64-js
    │   │   ├── bl
    │   │   ├── body-parser
    │   │   ├── boolean
    │   │   ├── brace-expansion
    │   │   ├── buffer
    │   │   ├── buffer-crc32
    │   │   ├── buffer-from
    │   │   ├── builder-util
    │   │   ├── builder-util-runtime
    │   │   ├── busboy
    │   │   ├── bytes
    │   │   ├── cacache
    │   │   ├── cacheable-lookup
    │   │   ├── cacheable-request
    │   │   ├── call-bind-apply-helpers
    │   │   ├── call-bound
    │   │   ├── chalk
    │   │   ├── chownr
    │   │   ├── chromium-pickle-js
    │   │   ├── ci-info
    │   │   ├── cli-cursor
    │   │   ├── cli-spinners
    │   │   ├── cli-truncate
    │   │   ├── cliui
    │   │   ├── clone
    │   │   ├── clone-response
    │   │   ├── color-convert
    │   │   ├── color-name
    │   │   ├── combined-stream
    │   │   ├── commander
    │   │   ├── compare-version
    │   │   ├── concat-map
    │   │   ├── concat-stream
    │   │   ├── content-disposition
    │   │   ├── content-type
    │   │   ├── cookie
    │   │   ├── cookie-signature
    │   │   ├── core-util-is
    │   │   ├── cors
    │   │   ├── crc
    │   │   ├── cross-dirname
    │   │   ├── cross-spawn
    │   │   ├── debug
    │   │   ├── decompress-response
    │   │   ├── defaults
    │   │   ├── defer-to-connect
    │   │   ├── define-data-property
    │   │   ├── define-properties
    │   │   ├── delayed-stream
    │   │   ├── depd
    │   │   ├── destroy
    │   │   ├── detect-libc
    │   │   ├── detect-node
    │   │   ├── dir-compare
    │   │   ├── dmg-builder
    │   │   ├── dmg-license
    │   │   ├── dotenv
    │   │   ├── dotenv-expand
    │   │   ├── dunder-proto
    │   │   ├── eastasianwidth
    │   │   ├── ee-first
    │   │   ├── ejs
    │   │   ├── electron
    │   │   ├── electron-builder
    │   │   ├── electron-builder-squirrel-windows
    │   │   ├── electron-publish
    │   │   ├── electron-winstaller
    │   │   ├── emoji-regex
    │   │   ├── encodeurl
    │   │   ├── encoding
    │   │   ├── end-of-stream
    │   │   ├── env-paths
    │   │   ├── err-code
    │   │   ├── es-define-property
    │   │   ├── es-errors
    │   │   ├── es-object-atoms
    │   │   ├── es-set-tostringtag
    │   │   ├── es6-error
    │   │   ├── escalade
    │   │   ├── escape-html
    │   │   ├── escape-string-regexp
    │   │   ├── etag
    │   │   ├── eventsource
    │   │   ├── eventsource-parser
    │   │   ├── exponential-backoff
    │   │   ├── express
    │   │   ├── express-rate-limit
    │   │   ├── extract-zip
    │   │   ├── extsprintf
    │   │   ├── fast-deep-equal
    │   │   ├── fast-json-stable-stringify
    │   │   ├── fast-uri
    │   │   ├── fd-slicer
    │   │   ├── fdir
    │   │   ├── filelist
    │   │   ├── finalhandler
    │   │   ├── foreground-child
    │   │   ├── form-data
    │   │   ├── forwarded
    │   │   ├── fresh
    │   │   ├── fs-extra
    │   │   ├── fs-minipass
    │   │   ├── fs.realpath
    │   │   ├── function-bind
    │   │   ├── get-caller-file
    │   │   ├── get-intrinsic
    │   │   ├── get-proto
    │   │   ├── get-stream
    │   │   ├── glob
    │   │   ├── global-agent
    │   │   ├── globalthis
    │   │   ├── gopd
    │   │   ├── got
    │   │   ├── graceful-fs
    │   │   ├── has-flag
    │   │   ├── has-property-descriptors
    │   │   ├── has-symbols
    │   │   ├── has-tostringtag
    │   │   ├── hasown
    │   │   ├── hono
    │   │   ├── hosted-git-info
    │   │   ├── http-cache-semantics
    │   │   ├── http-errors
    │   │   ├── http-proxy-agent
    │   │   ├── http2-wrapper
    │   │   ├── https-proxy-agent
    │   │   ├── iconv-corefoundation
    │   │   ├── iconv-lite
    │   │   ├── ieee754
    │   │   ├── imurmurhash
    │   │   ├── inflight
    │   │   ├── inherits
    │   │   ├── ip-address
    │   │   ├── ipaddr.js
    │   │   ├── is-fullwidth-code-point
    │   │   ├── is-interactive
    │   │   ├── is-promise
    │   │   ├── is-unicode-supported
    │   │   ├── isbinaryfile
    │   │   ├── isexe
    │   │   ├── jackspeak
    │   │   ├── jake
    │   │   ├── jiti
    │   │   ├── jose
    │   │   ├── js-yaml
    │   │   ├── json-buffer
    │   │   ├── json-schema-traverse
    │   │   ├── json-schema-typed
    │   │   ├── json-stringify-safe
    │   │   ├── json5
    │   │   ├── jsonfile
    │   │   ├── keyv
    │   │   ├── lazy-val
    │   │   ├── lodash
    │   │   ├── log-symbols
    │   │   ├── lowercase-keys
    │   │   ├── lru-cache
    │   │   ├── make-fetch-happen
    │   │   ├── matcher
    │   │   ├── math-intrinsics
    │   │   ├── media-typer
    │   │   ├── merge-descriptors
    │   │   ├── methods
    │   │   ├── mime
    │   │   ├── mime-db
    │   │   ├── mime-types
    │   │   ├── mimic-fn
    │   │   ├── mimic-response
    │   │   ├── minimatch
    │   │   ├── minimist
    │   │   ├── minipass
    │   │   ├── minipass-collect
    │   │   ├── minipass-fetch
    │   │   ├── minipass-flush
    │   │   ├── minipass-pipeline
    │   │   ├── minipass-sized
    │   │   ├── minizlib
    │   │   ├── mkdirp
    │   │   ├── ms
    │   │   ├── multer
    │   │   ├── negotiator
    │   │   ├── node-abi
    │   │   ├── node-addon-api
    │   │   ├── node-api-version
    │   │   ├── node-gyp
    │   │   ├── nopt
    │   │   ├── normalize-url
    │   │   ├── object-assign
    │   │   ├── object-inspect
    │   │   ├── object-keys
    │   │   ├── on-finished
    │   │   ├── once
    │   │   ├── onetime
    │   │   ├── ora
    │   │   ├── p-cancelable
    │   │   ├── p-limit
    │   │   ├── p-map
    │   │   ├── package-json-from-dist
    │   │   ├── parseurl
    │   │   ├── path-is-absolute
    │   │   ├── path-key
    │   │   ├── path-scurry
    │   │   ├── path-to-regexp
    │   │   ├── pe-library
    │   │   ├── pend
    │   │   ├── picocolors
    │   │   ├── picomatch
    │   │   ├── pkce-challenge
    │   │   ├── plist
    │   │   ├── postject
    │   │   ├── proc-log
    │   │   ├── progress
    │   │   ├── promise-retry
    │   │   ├── proper-lockfile
    │   │   ├── proxy-addr
    │   │   ├── pump
    │   │   ├── punycode
    │   │   ├── qs
    │   │   ├── quick-lru
    │   │   ├── range-parser
    │   │   ├── raw-body
    │   │   ├── read-binary-file-arch
    │   │   ├── readable-stream
    │   │   ├── require-directory
    │   │   ├── require-from-string
    │   │   ├── resedit
    │   │   ├── resolve-alpn
    │   │   ├── responselike
    │   │   ├── restore-cursor
    │   │   ├── retry
    │   │   ├── rimraf
    │   │   ├── roarr
    │   │   ├── router
    │   │   ├── safe-buffer
    │   │   ├── safer-buffer
    │   │   ├── sanitize-filename
    │   │   ├── sax
    │   │   ├── semver
    │   │   ├── semver-compare
    │   │   ├── send
    │   │   ├── serialize-error
    │   │   ├── serve-static
    │   │   ├── setprototypeof
    │   │   ├── shebang-command
    │   │   ├── shebang-regex
    │   │   ├── side-channel
    │   │   ├── side-channel-list
    │   │   ├── side-channel-map
    │   │   ├── side-channel-weakmap
    │   │   ├── signal-exit
    │   │   ├── simple-update-notifier
    │   │   ├── slice-ansi
    │   │   ├── smart-buffer
    │   │   ├── socks
    │   │   ├── socks-proxy-agent
    │   │   ├── source-map
    │   │   ├── source-map-support
    │   │   ├── sprintf-js
    │   │   ├── ssri
    │   │   ├── stat-mode
    │   │   ├── statuses
    │   │   ├── streamsearch
    │   │   ├── string_decoder
    │   │   ├── string-width
    │   │   ├── string-width-cjs
    │   │   ├── strip-ansi
    │   │   ├── strip-ansi-cjs
    │   │   ├── sumchecker
    │   │   ├── supports-color
    │   │   ├── tar
    │   │   ├── temp
    │   │   ├── temp-file
    │   │   ├── tiny-async-pool
    │   │   ├── tinyglobby
    │   │   ├── tmp
    │   │   ├── tmp-promise
    │   │   ├── toidentifier
    │   │   ├── truncate-utf8-bytes
    │   │   ├── type-fest
    │   │   ├── type-is
    │   │   ├── typedarray
    │   │   ├── undici-types
    │   │   ├── unique-filename
    │   │   ├── unique-slug
    │   │   ├── universalify
    │   │   ├── unpipe
    │   │   ├── uri-js
    │   │   ├── utf8-byte-length
    │   │   ├── util-deprecate
    │   │   ├── utils-merge
    │   │   ├── vary
    │   │   ├── verror
    │   │   ├── wcwidth
    │   │   ├── which
    │   │   ├── wrap-ansi
    │   │   ├── wrap-ansi-cjs
    │   │   ├── wrappy
    │   │   ├── xmlbuilder
    │   │   ├── y18n
    │   │   ├── yallist
    │   │   ├── yargs
    │   │   ├── yargs-parser
    │   │   ├── yauzl
    │   │   ├── yocto-queue
    │   │   ├── zod
    │   │   └── zod-to-json-schema
    │   ├── nohup.out
    │   ├── package-lock.json
    │   ├── package.json
    │   ├── README.md
    │   ├── start_ui_only.sh
    │   ├── start-fresh.sh
    │   ├── start.sh
    │   ├── stop.sh
    │   ├── discovery-workspace-export-2026-04-20.json
    │   └── ui
    │       ├── __pycache__
    │       ├── agent_workspace.html
    │       ├── assets
    │       └── discovery_ui.html
    ├── garage-main
    │   ├── __pycache__
    │   │   └── main.cpython-312.pyc
    │   ├── api
    │   │   ├── __pycache__
    │   │   ├── assistants.py
    │   │   ├── chat.py
    │   │   ├── files.py
    │   │   ├── knowledge_router.py
    │   │   ├── prompt_engineer.py
    │   │   ├── schemas.py
    │   │   ├── threads.py
    │   │   └── tools.py
    │   ├── AUDIT.md
    │   ├── BUSINESS_PLAN.md
    │   ├── config
    │   │   ├── __pycache__
    │   │   ├── qdrant_config.py
    │   │   └── settings.py
    │   ├── core
    │   │   ├── __pycache__
    │   │   ├── assistant.py
    │   │   ├── embeddings.py
    │   │   ├── file_processor.py
    │   │   ├── file_utils.py
    │   │   ├── ingestion
    │   │   ├── local_llm.py
    │   │   ├── memory.py
    │   │   └── qdrant_client.py
    │   ├── crawler
    │   ├── crawler_output
    │   ├── data
    │   │   ├── assistants
    │   │   ├── collections
    │   │   ├── diagrams
    │   │   ├── files
    │   │   ├── jurisprudencia_exemplo.csv
    │   │   ├── prompts
    │   │   ├── startup_log.md
    │   │   ├── threads
    │   │   └── tools
    │   ├── deploy
    │   │   └── garage.service
    │   ├── Dockerfile
    │   ├── docs
    │   │   ├── collection_data_info
    │   │   ├── IMPLEMENTATION_SUMMARY.md
    │   │   ├── PROJECT_COPY_REPORT.json
    │   │   ├── PROJECT_OVERVIEW.md
    │   │   ├── QDRANT_API_GUIDE.md
    │   │   ├── QUICK_REFERENCE.md
    │   │   ├── README-LEGAL-INGESTION.md
    │   │   ├── README-QDRANT.md
    │   │   ├── TRANSCRIPT_INGESTION_GUIDE.md
    │   │   └── TRANSCRIPT_SYSTEM_README.md
    │   ├── export_functionalities_collections-qdrant.md
    │   ├── logs
    │   ├── main.py
    │   ├── mcp
    │   │   ├── catalog
    │   │   ├── generate_tool_catalog.py
    │   │   ├── health_check.sh
    │   │   ├── MCP_ARCHITECTURE.md
    │   │   ├── MCP_READINESS_CHECKLIST_2026-04-25.md
    │   │   ├── MCP_READINESS_REPORT_2026-04-24.md
    │   │   ├── mcpServers.example.json
    │   │   ├── mcpServers.local.json
    │   │   ├── README.md
    │   │   ├── requirements.txt
    │   │   ├── servers
    │   │   └── start_server.sh
    │   ├── meshy
    │   │   ├── meshy_animation_cards_sample.html
    │   │   ├── meshy-animation-catalog.json
    │   │   └── meshy-ui.js
    │   ├── PROJECT_STATUS.md
    │   ├── README.md
    │   ├── requirements.txt
    │   ├── routes
    │   │   ├── __init__.py
    │   │   ├── __pycache__
    │   │   ├── ingestion.py
    │   │   ├── legal_doc_ingestion_v2.py
    │   │   ├── legal_document_processor.py
    │   │   ├── legal_ingestion.py
    │   │   ├── qdrant_router.py
    │   │   └── transcript_ingestion.py
    │   ├── schemas
    │   │   └── qdrant_schemas.py
    │   ├── scripts
    │   │   ├── __pycache__
    │   │   ├── build_unirg_navigable.py
    │   │   ├── check_qdrant_health.py
    │   │   ├── embed_case_dir_runner.py
    │   │   ├── ingest_legal_csv.py
    │   │   ├── quickstart_legal_ingestion.sh
    │   │   ├── reproduce_deepseek.py
    │   │   ├── test_chunking.py
    │   │   ├── test_doc_extraction.py
    │   │   ├── test_empty_filter.py
    │   │   ├── transcript_analyzer.py
    │   │   ├── unirg-sidebar-scraper.py
    │   │   ├── website-crawler-gpi.py
    │   │   ├── website-crawler-rs.py
    │   │   └── website-crawler.py
    │   ├── services
    │   │   ├── __pycache__
    │   │   ├── embedding_service.py
    │   │   ├── legal_doc_processor.py
    │   │   ├── legal_document_ingestor.py
    │   │   ├── legal_qdrant_config.py
    │   │   ├── qdrant_client.py
    │   │   ├── qdrant_service.py
    │   │   └── watch_frameworks.py
    │   ├── start_all.sh
    │   ├── start.sh
    │   ├── static
    │   │   ├── css
    │   │   └── js
    │   ├── templates
    │   │   ├── garage.html
    │   │   ├── pinocchio.html
    │   │   └── qdrant.html
    │   └── utils
    │       ├── __pycache__
    │       ├── document_ingestor.py
    │       ├── document_processor.py
    │       └── legal_csv_processor.py
    └── transcription
        ├── ARCHITECTURE.md
        ├── AUDIT_REPORT.md
        ├── data
        │   ├── audio
        │   ├── originals
        │   ├── queue.json
        │   ├── transcripts
        │   └── transcripts_by_audio
        ├── deploy
        │   └── pinocchio.service
        ├── docker-compose.yml
        ├── Dockerfile
        ├── docs
        │   ├── awareness-forensic-transcription-agent.agent.md
        │   ├── mcp-servers.example.json
        │   └── REFERENCE_GUIDED_TRANSCRIPTION.md
        ├── information_for_env.md
        ├── install
        ├── Makefile
        ├── mcp
        │   ├── __pycache__
        │   ├── generate_readiness_report.py
        │   ├── MCP_ARCHITECTURE.md
        │   ├── MCP_BOOTSTRAP_STANDARD.md
        │   ├── MCP_READINESS_REPORT.md
        │   ├── mcpServers.example.json
        │   ├── README.md
        │   └── servers
        ├── patch_script.sh
        ├── patch_test.py
        ├── pyproject.toml
        ├── README.md
        ├── requirements.txt
        ├── run.sh
        ├── runpod_client_example.js
        ├── runpod_client_example.py
        ├── RUNPOD_SETUP.md
        ├── scripts
        │   ├── batch_transcribe.py
        │   ├── bootstrap_runpod_pod.sh
        │   ├── identify_speakers.py
        │   ├── inspect_transcripts.py
        │   ├── organize_references.py
        │   └── setup_github_runpod.sh
        ├── setup_runpod_endpoint.sh
        ├── smoke_test_mcp.py
        ├── src
        │   ├── __pycache__
        │   ├── application
        │   ├── composition.py
        │   ├── config.py
        │   ├── domain
        │   ├── infrastructure
        │   ├── logging_setup.py
        │   ├── main.py
        │   ├── mcp
        │   ├── presentation
        │   └── runpod_handler.py
        └── tests
            ├── __init__.py
            ├── integration
            └── unit

1124 directories, 434 files

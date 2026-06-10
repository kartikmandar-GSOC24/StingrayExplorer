module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: {
    react: { version: 'detect' },
  },
  ignorePatterns: ['dist', 'dist-electron', 'node_modules'],
  rules: {
    // Vite's automatic JSX runtime makes React imports unnecessary
    'react/react-in-jsx-scope': 'off',
    // TypeScript types make prop-types redundant
    'react/prop-types': 'off',
    // Downgraded: existing code uses `any` in a few places; flag without failing the build
    '@typescript-eslint/no-explicit-any': 'warn',
    // Downgraded: existing code has unused vars; `_`-prefix is the in-repo convention
    // for intentionally unused bindings, so ignore those entirely
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // Stylistic: literal quotes in JSX prose are fine in this app
    'react/no-unescaped-entities': 'off',
  },
};

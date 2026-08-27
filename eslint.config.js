module.exports = [
  {
    files: ["location_floor_plan/static/location_floor_plan/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2021,
      sourceType: "script",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        fetch: "readonly",
        FormData: "readonly",
        L: "readonly",
        setTimeout: "readonly"
      }
    },
    rules: {
      "no-unused-vars": ["error", { "args": "none" }]
    }
  }
];

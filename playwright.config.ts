import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/ux",
  timeout: 30000,
  use: {
    baseURL: "http://localhost:8080",
    screenshot: "only-on-failure",
    video: "off",
  },
  webServer: {
    command: "python -m http.server 8080",
    url: "http://localhost:8080",
    reuseExistingServer: !process.env.CI,
    timeout: 10000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});

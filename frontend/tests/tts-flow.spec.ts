import { test, expect } from '@playwright/test';

// Utility to create a tiny fake MP3 blob so decoding doesn't throw a format error
// A valid empty ID3 metadata MP3 will do, but a text blob is fine if the code handles decode failure.
// actually, let's inject a valid minimal base64 mp3:
const minimalMp3Base64 = "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU5LjI3LjEwMAAAAAAAAAAAAAAA//OEAAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAAEAAABIwBRUVFRUVFRUVFRUVFRUVFRUVFRUVFRVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVWVlZWVlZWVlZWVlZWVlZWVlZWVlZWVlZXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmbm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5uqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqru7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7/8AAAAATGF2YzU5LjM3AAAAAAAAAAAAAAAAJAAAAAAAAAAAASO5oRygAAAAAP/zBAxA";

async function mockDetectLanguage(page: any) {
  await page.route('/api/detect-language', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ language: 'en-US' }),
    });
  });
}

async function mockVoices(page: any) {
  await page.route('/api/voices*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        language: 'en-US',
        voices: [
          { short_name: 'en-US-GuyNeural', gender: 'Male', locale: 'en-US' },
          { short_name: 'en-US-AriaNeural', gender: 'Female', locale: 'en-US' },
        ],
      }),
    });
  });
}

async function mockTTS(page: any, delayMs = 0) {
  await page.route('/api/tts', async (route) => {
    if (delayMs > 0) {
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }
    const buffer = Buffer.from(minimalMp3Base64, 'base64');
    await route.fulfill({
      status: 200,
      contentType: 'audio/mpeg',
      body: buffer,
    });
  });
}

test.describe('TTS Web Frontend Flow', () => {

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      // Mock AudioContext to always return a duration of 120 seconds (02:00)
      (window as any).AudioContext = class {
        decodeAudioData() {
          return Promise.resolve({ duration: 120 });
        }
        close() {}
      };
      (window as any).webkitAudioContext = (window as any).AudioContext;
    });

    await mockDetectLanguage(page);
    await mockVoices(page);
    // Don't mock TTS by default, do it per test if we want delays
    await page.goto('/');
  });

  test('1. Language detection flow', async ({ page }) => {
    const textarea = page.locator('textarea#tts-text-input');
    await textarea.fill('Hello world test text string');

    const detectBtn = page.locator('button#detect-language-button');
    await expect(detectBtn).toBeVisible();
    await detectBtn.click();

    // Check Voice selector appeared
    const voiceSelectLabel = page.locator('label', { hasText: 'Voice' });
    await expect(voiceSelectLabel).toBeVisible();
    
    // Detect Language button should disappear
    await expect(detectBtn).toBeHidden();

    // Generate MP3 button should appear
    const generateBtn = page.locator('button#generate-button');
    await expect(generateBtn).toBeVisible();
  });

  test('2. Generation with progress', async ({ page }) => {
    await mockTTS(page, 2000); // 2 second delay to see progress

    await page.locator('textarea#tts-text-input').fill('Hello world test text string');
    await page.locator('button#detect-language-button').click();
    
    await page.locator('button#generate-button').click();

    // Check progress UI
    const progressStatus = page.locator('.progress__status');
    await expect(progressStatus).toBeVisible();
    await expect(progressStatus).toContainText('Sending request…');

    const progressTime = page.locator('.progress__time');
    await expect(progressTime).toBeVisible();
    await expect(progressTime).toContainText(':'); // e.g. "00:00" or "00:01"
  });

  test('3. Clear after generation', async ({ page }) => {
    await mockTTS(page, 0); // Instant

    await page.locator('textarea#tts-text-input').fill('Hello world test text string');
    await page.locator('button#detect-language-button').click();
    await page.locator('button#generate-button').click();

    // Wait for done
    await expect(page.locator('#download-button')).toBeVisible();

    // Click Clear
    await page.locator('button#clear-button').click();

    // Assert initial state
    await expect(page.locator('textarea#tts-text-input')).toHaveValue('');
    await expect(page.locator('button#generate-button')).toBeHidden();
    await expect(page.locator('.progress')).toBeHidden();
    await expect(page.locator('#download-button')).toBeHidden();
  });

  test('4. Download info (size + duration)', async ({ page }) => {
    await mockTTS(page, 0);

    await page.locator('textarea#tts-text-input').fill('Hello world test text string');
    await page.locator('button#detect-language-button').click();
    await page.locator('button#generate-button').click();

    const hint = page.locator('.download__hint');
    await expect(hint).toBeVisible();
    
    // Base64 file is very small, likely under 1KB so formats to "xxx B"
    await expect(hint).toContainText('B'); 
    
    // Duration is 120 seconds (mocked in AudioContext), so it formats to 02:00
    await expect(hint).toContainText('02:00'); 
  });

  test('5. Cancel during generation', async ({ page }) => {
    // Large delay so we can cancel it
    await mockTTS(page, 10000);

    await page.locator('textarea#tts-text-input').fill('Cancel this string right now please');
    await page.locator('button#detect-language-button').click();
    await page.locator('button#generate-button').click();

    // Expect progress to appear
    await expect(page.locator('.progress')).toBeVisible();

    // Click Clear
    await page.locator('button#clear-button').click();

    // Check reset state: no progress, textarea empty
    await expect(page.locator('.progress')).toBeHidden();
    await expect(page.locator('textarea#tts-text-input')).toHaveValue('');
  });

  test('6. Filename format', async ({ page }) => {
    await mockTTS(page, 0);

    await page.locator('textarea#tts-text-input').fill('Hello world test text string');
    await page.locator('button#detect-language-button').click();

    // Trigger download but intercept it immediately
    const downloadPromise = page.waitForEvent('download');
    await page.locator('button#generate-button').click();

    // Wait for generation to finish and then click the newly-appeared download button
    await page.locator('#download-button').click();

    const download = await downloadPromise;
    const filename = download.suggestedFilename();
    
    // Format: long_text_to_speech_{DD.MM.YYYY}_{HH.MM.SS}.mp3
    expect(filename).toMatch(/^long_text_to_speech_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}\.mp3$/);
  });

  test('7. Hide buttons if text is less than 5 words or removed', async ({ page }) => {
    await mockTTS(page, 0);
    // Start with 4 words
    const textarea = page.locator('textarea#tts-text-input');
    await textarea.fill('One two three four');
    
    const detectBtn = page.locator('button#detect-language-button');
    await expect(detectBtn).toBeHidden();
    
    // Fill 5 words
    await textarea.fill('One two three four five');
    await expect(detectBtn).toBeVisible();
    
    // Detect and show Generate MP3
    await detectBtn.click();
    const generateBtn = page.locator('button#generate-button');
    await expect(generateBtn).toBeVisible();
    
    // Remove text down to 4 words
    await textarea.fill('One two three four');
    
    // Both buttons should be hidden
    await expect(detectBtn).toBeHidden();
    await expect(generateBtn).toBeHidden();
  });

  test('8. Show processing state during language detection', async ({ page }) => {
    // Unroute the default mock and add a delayed one
    await page.unroute('/api/detect-language');
    await page.route('/api/detect-language', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ language: 'en-US' }),
      });
    });

    const textarea = page.locator('textarea#tts-text-input');
    await textarea.fill('One two three four five');
    
    const detectBtn = page.locator('button#detect-language-button');
    await expect(detectBtn).toBeVisible();
    await expect(detectBtn).toHaveText('Detect Language');
    
    // Click and immediately check text
    const clickPromise = detectBtn.click();
    await expect(detectBtn).toHaveText('Detecting…');
    await expect(detectBtn).toBeDisabled();
    await clickPromise;
    
    // Wait for it to finish and disappear
    await expect(detectBtn).toBeHidden();
  });

});

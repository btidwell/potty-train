import { Amplify } from 'aws-amplify';
import {
  autoSignIn,
  confirmResetPassword,
  confirmSignIn,
  confirmSignUp,
  fetchAuthSession,
  fetchDevices,
  rememberDevice,
  resendSignUpCode,
  resetPassword,
  signIn,
  signOut,
  signUp,
  updateMFAPreference,
  type SignInOutput,
} from 'aws-amplify/auth';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import { CookieStorage } from 'aws-amplify/utils';
import QRCode from 'qrcode';

export type AuthView =
  | { kind: 'signed-in' }
  | { kind: 'confirm-email' }
  | { kind: 'new-password' }
  | { kind: 'totp-setup'; secret: string; qr: string }
  | { kind: 'totp-code' };

let ready: Promise<void> | null = null;
let authenticatorRecord: Promise<void> | null = null;

export function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

export function passwordProblem(password: string): string {
  if (password.length < 12) {
    return 'Use at least 12 characters.';
  }
  if (!/[a-z]/.test(password)) {
    return 'Include a lowercase letter.';
  }
  if (!/[A-Z]/.test(password)) {
    return 'Include an uppercase letter.';
  }
  if (!/[0-9]/.test(password)) {
    return 'Include a number.';
  }
  if (!/[^A-Za-z0-9]/.test(password)) {
    return 'Include a symbol.';
  }
  return '';
}

export function authMessage(error: unknown, fallback: string): string {
  const name = errorName(error);
  const message = errorText(error);
  switch (name) {
    case 'UserNotConfirmedException':
      return 'Enter the code from your email before signing in.';
    case 'NotAuthorizedException':
      return 'Email or password is wrong.';
    case 'UsernameExistsException':
      return 'That email already has an account. Sign in instead.';
    case 'CodeMismatchException':
    case 'EnableSoftwareTokenMFAException':
      return 'That code is wrong.';
    case 'ExpiredCodeException':
      return 'That code expired. Send a new one.';
    case 'InvalidPasswordException':
      return message || 'Choose a stronger password.';
    case 'LimitExceededException':
    case 'TooManyRequestsException':
    case 'TooManyFailedAttemptsException':
      return 'Too many tries. Wait a few minutes and try again.';
    default:
      return message || fallback;
  }
}

export function configureAuth(): Promise<void> {
  if (!ready) {
    ready = loadConfig();
  }
  return ready;
}

export async function accessToken(forceRefresh = false): Promise<string> {
  await configureAuth();
  const session = await fetchAuthSession(forceRefresh ? { forceRefresh: true } : {});
  return session.tokens?.accessToken?.toString() ?? '';
}

export async function endSession(): Promise<void> {
  await configureAuth();
  // Revoke this browser's refresh token. Other signed-in devices stay up
  // until they are removed from Settings.
  await signOut();
}

export function deviceLabel(): string {
  const agent = navigator.userAgent;
  const browser = /Edg\//.test(agent)
    ? 'Edge'
    : /Chrome\//.test(agent)
      ? 'Chrome'
      : /Firefox\//.test(agent)
        ? 'Firefox'
        : /Safari\//.test(agent)
          ? 'Safari'
          : 'Browser';
  const system = /Windows/.test(agent)
    ? 'Windows'
    : /Android/.test(agent)
      ? 'Android'
      : /iPhone|iPad/.test(agent)
        ? 'iPhone or iPad'
        : /Mac OS/.test(agent)
          ? 'Mac'
          : 'this device';
  return `${browser} on ${system}`;
}

export async function rememberThisDevice(): Promise<string> {
  await configureAuth();
  await rememberDevice();
  return currentDeviceKey();
}

export async function currentDeviceKey(): Promise<string> {
  try {
    await configureAuth();
    const devices = await fetchDevices();
    const newest = [...devices].sort(
      (left, right) => (right.lastAuthenticatedDate?.getTime() ?? 0) - (left.lastAuthenticatedDate?.getTime() ?? 0),
    )[0];
    return newest?.id ?? '';
  } catch {
    return '';
  }
}

export async function deviceIsRemembered(deviceKey: string): Promise<boolean> {
  if (!deviceKey) {
    return false;
  }
  try {
    await configureAuth();
    const devices = await fetchDevices();
    return devices.some((device) => device.id === deviceKey && device.attributes?.['device_status'] === 'remembered');
  } catch {
    return false;
  }
}

export async function signInWithPassword(email: string, password: string): Promise<AuthView> {
  await configureAuth();
  try {
    return await interpret(await signIn({ username: email, password }));
  } catch (error) {
    if (errorName(error) === 'UserAlreadyAuthenticatedException') {
      return { kind: 'signed-in' };
    }
    throw error;
  }
}

export async function createAccount(email: string, password: string): Promise<'confirm-email'> {
  await configureAuth();
  const result = await signUp({
    username: email,
    password,
    options: {
      userAttributes: { email },
      autoSignIn: true,
    },
  });
  if (result.nextStep.signUpStep === 'CONFIRM_SIGN_UP' || result.nextStep.signUpStep === 'DONE') {
    return 'confirm-email';
  }
  return 'confirm-email';
}

export async function confirmEmail(email: string, code: string): Promise<AuthView | 'sign-in'> {
  await configureAuth();
  const confirmed = await confirmSignUp({ username: email, confirmationCode: code });
  if (confirmed.nextStep.signUpStep === 'COMPLETE_AUTO_SIGN_IN') {
    return interpret(await autoSignIn());
  }
  return 'sign-in';
}

export async function resendEmailCode(email: string): Promise<void> {
  await configureAuth();
  await resendSignUpCode({ username: email });
}

export async function confirmNewPassword(password: string): Promise<AuthView> {
  await configureAuth();
  return interpret(await confirmSignIn({ challengeResponse: password }));
}

export async function confirmAuthenticator(code: string): Promise<AuthView> {
  await configureAuth();
  return interpret(await confirmSignIn({ challengeResponse: code }));
}

export function recordAuthenticator(): Promise<void> {
  // Restore runs from startup and from the route guard together. Cognito accepts
  // only one MFA preference update at a time, so those calls share one request.
  if (!authenticatorRecord) {
    authenticatorRecord = saveAuthenticatorPreference();
  }
  return authenticatorRecord;
}

async function saveAuthenticatorPreference(): Promise<void> {
  try {
    await configureAuth();
    await updateMFAPreference({ totp: 'PREFERRED' });
  } catch {
    authenticatorRecord = null;
  }
}

export async function sendPasswordReset(email: string): Promise<void> {
  await configureAuth();
  await resetPassword({ username: email });
}

export async function signedInAsOwner(): Promise<boolean> {
  try {
    await configureAuth();
    const session = await fetchAuthSession({ forceRefresh: true });
    const groups = session.tokens?.accessToken?.payload?.['cognito:groups'];
    return Array.isArray(groups) && groups.includes('owners');
  } catch {
    return false;
  }
}

export async function finishPasswordReset(email: string, code: string, password: string): Promise<void> {
  await configureAuth();
  await confirmResetPassword({ username: email, confirmationCode: code, newPassword: password });
}

async function loadConfig(): Promise<void> {
  const response = await fetch('/api/auth-config');
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.userPoolId || !body.userPoolClientId) {
    ready = null;
    throw new Error(body.error || 'Sign-in is not configured.');
  }
  const sessionDays = Number(body.sessionDays) || 7;
  cognitoUserPoolsTokenProvider.setKeyValueStorage(
    new CookieStorage({
      path: '/',
      expires: sessionDays,
      sameSite: 'strict',
      secure: window.location.protocol === 'https:',
    }),
  );
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: String(body.userPoolId),
        userPoolClientId: String(body.userPoolClientId),
      },
    },
  });
}

async function interpret(result: SignInOutput): Promise<AuthView> {
  const next = result.nextStep;
  switch (next.signInStep) {
    case 'DONE':
      return { kind: 'signed-in' };
    case 'CONFIRM_SIGN_UP':
      return { kind: 'confirm-email' };
    case 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED':
      return { kind: 'new-password' };
    case 'CONFIRM_SIGN_IN_WITH_TOTP_CODE':
      return { kind: 'totp-code' };
    case 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP': {
      const details = next.totpSetupDetails;
      const uri = details.getSetupUri('Potty Log').toString();
      const qr = await QRCode.toDataURL(uri, { margin: 1, width: 220 });
      return { kind: 'totp-setup', secret: details.sharedSecret, qr };
    }
    default:
      throw new Error('This sign-in step is not supported.');
  }
}

function errorName(error: unknown): string {
  if (error && typeof error === 'object' && 'name' in error) {
    return String(error.name);
  }
  return '';
}

function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String(error.message);
  }
  return '';
}

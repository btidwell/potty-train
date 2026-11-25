import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { Api } from './api';

export const authGuard: CanActivateFn = async () => {
  const api = inject(Api);
  const router = inject(Router);
  if (await api.restore()) {
    return true;
  }
  return router.createUrlTree(['/login']);
};

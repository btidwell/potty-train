import { Routes } from '@angular/router';
import { authGuard } from './auth.guard';
import { GuidePage } from './guide';
import { LoginPage } from './login';
import { NowPage } from './now';
import { SettingsPage } from './settings';
import { SheetPage } from './sheet';

export const routes: Routes = [
  { path: 'login', component: LoginPage },
  { path: '', canActivate: [authGuard], children: [
    { path: '', pathMatch: 'full', redirectTo: 'now' },
    { path: 'now', component: NowPage },
    { path: 'sheet', component: SheetPage },
    { path: 'guide', component: GuidePage },
    { path: 'settings', component: SettingsPage },
  ] },
  { path: '**', redirectTo: 'now' },
];

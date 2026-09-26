import React from 'react';
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router-dom';
import { AppProvider, useApp, ROLES, landingPathFor } from './context/AppContext';
import { AppLayout } from './layouts/AppLayout';
import { CommandPalette } from './components/CommandPalette';
import { Toast } from './components/UI';

// Super Admin Pages
import { SuperAdminDashboard } from './pages/SuperAdminDashboard';
import { AgencyManagement } from './pages/AgencyManagement';
import { BusinessManagement } from './pages/BusinessManagement';
import { BusinessDetails } from './pages/BusinessDetails';
import { SuperAdminSettings } from './pages/SuperAdminSettings';

// Agency Admin Pages
import { AgencyAdminDashboard } from './pages/AgencyAdminDashboard';
import { AgencyAdminSettings } from './pages/AgencyAdminSettings';

// Customer Admin (business workspace) Pages
import { BusinessAdminDashboard } from './pages/BusinessAdminDashboard';
import { Contacts } from './pages/Contacts';
import { ImportWizard } from './pages/ImportWizard';
import { Groups } from './pages/Groups';
import { Templates } from './pages/Templates';
import { Campaigns } from './pages/Campaigns';
import { WhatsAppNumbers } from './pages/WhatsAppNumbers';
import { BusinessAdminSettings } from './pages/BusinessAdminSettings';
import { Login } from './pages/Login';

const BusinessDetailsWrapper = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  return <BusinessDetails bizId={id} onClose={() => navigate('/business-listing')} />;
};

/**
 * RoleRoute — guards a route so only the allowed roles can render it.
 * If the current role isn't allowed, it redirects to that role's landing page.
 * This prevents reaching another role's pages by typing the URL directly.
 */
const RoleRoute = ({ allow, currentRole, children }) => {
  if (!allow.includes(currentRole)) {
    return <Navigate to={landingPathFor(currentRole)} replace />;
  }
  return children;
};

const AppContent = () => {
  const { currentRole, toasts, isAuthenticated, authLoading } = useApp();

  // Show nothing while we try a silent token refresh on mount
  if (authLoading) return null;

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  const { SUPERADMIN, AGENCYADMIN, CUSTOMERADMIN } = ROLES;

  return (
    <AppLayout>
      <Routes>
        {/* ---------- Super Admin ---------- */}
        <Route path="/super-admin/dashboard" element={
          <RoleRoute allow={[SUPERADMIN]} currentRole={currentRole}><SuperAdminDashboard /></RoleRoute>
        } />
        <Route path="/agencies" element={
          <RoleRoute allow={[SUPERADMIN]} currentRole={currentRole}><AgencyManagement /></RoleRoute>
        } />
        <Route path="/super-admin/settings" element={
          <RoleRoute allow={[SUPERADMIN]} currentRole={currentRole}><SuperAdminSettings /></RoleRoute>
        } />

        {/* ---------- Agency Admin ---------- */}
        <Route path="/agency/dashboard" element={
          <RoleRoute allow={[AGENCYADMIN]} currentRole={currentRole}><AgencyAdminDashboard /></RoleRoute>
        } />
        <Route path="/agency/settings" element={
          <RoleRoute allow={[AGENCYADMIN]} currentRole={currentRole}><AgencyAdminSettings /></RoleRoute>
        } />

        {/* ---------- Businesses / Customers (superadmin: all, agencyadmin: scoped) ---------- */}
        <Route path="/business-listing" element={
          <RoleRoute allow={[SUPERADMIN, AGENCYADMIN]} currentRole={currentRole}><BusinessManagement /></RoleRoute>
        } />
        <Route path="/business-register" element={
          <RoleRoute allow={[SUPERADMIN, AGENCYADMIN]} currentRole={currentRole}><BusinessManagement /></RoleRoute>
        } />
        <Route path="/business-details/:id" element={
          <RoleRoute allow={[SUPERADMIN, AGENCYADMIN]} currentRole={currentRole}><BusinessDetailsWrapper /></RoleRoute>
        } />

        {/* ---------- Customer Admin (single business workspace) ---------- */}
        <Route path="/business/dashboard" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><BusinessAdminDashboard /></RoleRoute>
        } />
        <Route path="/contacts" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><Contacts /></RoleRoute>
        } />
        <Route path="/import" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><ImportWizard /></RoleRoute>
        } />
        <Route path="/groups" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><Groups /></RoleRoute>
        } />
        <Route path="/templates" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><Templates /></RoleRoute>
        } />
        <Route path="/campaigns" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><Campaigns /></RoleRoute>
        } />
        <Route path="/whatsapp-numbers" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><WhatsAppNumbers /></RoleRoute>
        } />
        <Route path="/business/settings" element={
          <RoleRoute allow={[CUSTOMERADMIN]} currentRole={currentRole}><BusinessAdminSettings /></RoleRoute>
        } />

        {/* ---------- Redirect / Fallback ---------- */}
        <Route path="/" element={<Navigate to={landingPathFor(currentRole)} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/* Global Command Palette Overlay (Ctrl+K) */}
      <CommandPalette />

      {/* Global Toast Alerts Stack */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((t) => (
          <Toast key={t.id} message={t.message} type={t.type} />
        ))}
      </div>
    </AppLayout>
  );
};

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default App;

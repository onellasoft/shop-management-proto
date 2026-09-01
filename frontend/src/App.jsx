import React from 'react';
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router-dom';
import { AppProvider, useApp, ROLES } from './context/AppContext';
import { AppLayout } from './layouts/AppLayout';
import { CommandPalette } from './components/CommandPalette';
import { Toast } from './components/UI';

// Super Admin Pages
import { SuperAdminDashboard } from './pages/SuperAdminDashboard';
import { BusinessManagement } from './pages/BusinessManagement';
import { BusinessDetails } from './pages/BusinessDetails';
import { SuperAdminSettings } from './pages/SuperAdminSettings';

// Business Admin Pages
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

  return (
    <AppLayout>
      <Routes>
        {/* Super Admin Routes */}
        <Route path="/super-admin/dashboard" element={<SuperAdminDashboard />} />
        <Route path="/business-listing" element={<BusinessManagement />} />
        <Route path="/business-register" element={<BusinessManagement />} />
        <Route path="/business-details/:id" element={<BusinessDetailsWrapper />} />
        <Route path="/super-admin/settings" element={<SuperAdminSettings />} />

        {/* Business Admin Routes */}
        <Route path="/business/dashboard" element={<BusinessAdminDashboard />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/import" element={<ImportWizard />} />
        <Route path="/groups" element={<Groups />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/whatsapp-numbers" element={<WhatsAppNumbers />} />
        <Route path="/business/settings" element={<BusinessAdminSettings />} />

        {/* Redirect / Fallback routes */}
        <Route path="/" element={<Navigate to={currentRole === ROLES.SUPERADMIN ? "/super-admin/dashboard" : "/business/dashboard"} replace />} />
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

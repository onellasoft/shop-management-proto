import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { login, requestOtp, verifyOtp } from '../lib/api';
import { Phone, KeyRound, ArrowRight, ShieldCheck, Building2, Mail, Lock, Eye, EyeOff } from 'lucide-react';

// Dev-mode quick-login entries — match the seeded users in app/scripts/seed.py
const DEV_QUICK_LOGINS = [
  {
    label: 'Agency Admin',
    hint: '+91 95613 11757',
    mobile: '+919561311757',
    email: 'superadmin@onella.test',
    icon: ShieldCheck,
    color: '#3B82F6',
  },
  {
    label: 'Business Admin',
    hint: '+91 75886 11478',
    mobile: '+917588611478',
    email: 'agencyadmin@onella.test',
    icon: Building2,
    color: '#8B5CF6',
  },
];

const isDev = import.meta.env.DEV;

// ---------------------------------------------------------------------------
// OTP input component
// ---------------------------------------------------------------------------
function OtpInput({ value, onChange, disabled }) {
  const digits = value.split('');
  while (digits.length < 6) digits.push('');

  const handleChange = (char, i) => {
    const clean = char.replace(/\D/g, '').slice(-1);
    const next = [...digits];
    next[i] = clean;
    onChange(next.join(''));
    if (clean && i < 5) document.getElementById(`otp-${i + 1}`)?.focus();
  };

  const handleKeyDown = (e, i) => {
    if (e.key === 'Backspace') {
      if (digits[i] === '' && i > 0) {
        const next = [...digits]; next[i - 1] = '';
        onChange(next.join(''));
        document.getElementById(`otp-${i - 1}`)?.focus();
      } else {
        const next = [...digits]; next[i] = '';
        onChange(next.join(''));
      }
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    onChange(pasted.padEnd(6, '').slice(0, 6));
    document.getElementById(`otp-${Math.min(5, pasted.length)}`)?.focus();
  };

  return (
    <div className="flex justify-between items-center gap-2 py-2">
      {digits.map((d, i) => (
        <input
          key={i}
          id={`otp-${i}`}
          type="text"
          inputMode="numeric"
          maxLength={1}
          value={d}
          onChange={(e) => handleChange(e.target.value, i)}
          onKeyDown={(e) => handleKeyDown(e, i)}
          onPaste={handlePaste}
          disabled={disabled}
          required
          className="w-12 bg-[#0E0F11] border border-[#27282A] focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] rounded-xl text-center text-lg font-bold text-white outline-none transition-all"
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main login page
// ---------------------------------------------------------------------------
export const Login = () => {
  const { handleLoginSuccess, addToast } = useApp();

  // Tab: 'otp' | 'email'
  const [tab, setTab] = useState('otp');

  // OTP flow
  const [mobile, setMobile]     = useState('');
  const [otpStep, setOtpStep]   = useState('phone'); // 'phone' | 'code'
  const [otpCode, setOtpCode]   = useState('');

  // Email/pass flow
  const [email, setEmail]         = useState('');
  const [password, setPassword]   = useState('');
  const [showPass, setShowPass]   = useState(false);

  // Shared
  const [error, setError]         = useState('');
  const [loading, setLoading]     = useState(false);

  const clearError = () => setError('');

  // ------------------------------------------------------------------
  // OTP flow handlers
  // ------------------------------------------------------------------
  const handleRequestOtp = async (e) => {
    e.preventDefault();
    clearError();
    const cleaned = mobile.replace(/\D/g, '');
    if (cleaned.length < 10) { setError('Enter a valid 10-digit mobile number.'); return; }

    setLoading(true);
    try {
      // The backend always returns 202 with a generic message regardless of
      // whether the mobile is registered — it never leaks account existence.
      await requestOtp(mobile.startsWith('+') ? mobile : `+91${cleaned}`);
      setOtpStep('code');
      addToast('OTP sent! Check your phone (or backend logs in dev).', 'info');
      setTimeout(() => document.getElementById('otp-0')?.focus(), 50);
    } catch (err) {
      setError(err.message ?? 'Failed to send OTP. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    clearError();
    if (otpCode.replace(/\D/g,'').length !== 6) { setError('Enter the 6-digit code.'); return; }

    setLoading(true);
    try {
      const cleaned = mobile.replace(/\D/g, '');
      const normalised = mobile.startsWith('+') ? mobile : `+91${cleaned}`;
      const tokenPair = await verifyOtp(normalised, otpCode);
      handleLoginSuccess(tokenPair);
    } catch (err) {
      if (err.status === 401) {
        setError('Invalid or expired OTP. Please try again.');
      } else {
        setError(err.message ?? 'Verification failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  // ------------------------------------------------------------------
  // Email/password flow handler
  // ------------------------------------------------------------------
  const handleEmailLogin = async (e) => {
    e.preventDefault();
    clearError();
    if (!email.trim() || !password) { setError('Enter your email and password.'); return; }

    setLoading(true);
    try {
      const tokenPair = await login(email.trim(), password);
      handleLoginSuccess(tokenPair);
    } catch (err) {
      if (err.status === 401) {
        setError('Invalid email or password.');
      } else if (err.status === 423) {
        setError('Account locked. Try again in 15 minutes.');
      } else {
        setError(err.message ?? 'Login failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  // ------------------------------------------------------------------
  // Quick-fill helpers
  // ------------------------------------------------------------------
  const fillMobile = (m) => { setMobile(m.replace('+91', '').replace(/\D/g,'')); clearError(); };
  const fillEmail  = (em) => { setEmail(em); setPassword('Password123!'); clearError(); };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-[#0E0F11] flex items-center justify-center p-6 font-sans relative overflow-hidden">
      {/* Background blobs */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-[#3B82F6]/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-[#8B5CF6]/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="w-full max-w-md bg-[#18191B] border border-[#27282A] rounded-2xl p-8 shadow-2xl relative z-10">

        {/* Brand */}
        <div className="flex flex-col items-center text-center mb-6">
          <div className="h-12 w-12 bg-white text-[#111111] font-extrabold flex items-center justify-center rounded-xl text-[24px] mb-3 shadow-lg">O</div>
          <h2 className="text-xl font-bold text-white tracking-tight">Welcome to Onella SaaS</h2>
          <p className="text-xs text-[#9CA3AF] mt-1">Sign in to manage your shops & messages</p>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-[#0E0F11] border border-[#27282A] rounded-xl p-1 mb-6">
          <button
            type="button"
            onClick={() => { setTab('otp'); clearError(); setOtpStep('phone'); }}
            className={`flex-1 text-xs font-semibold py-2 rounded-lg transition-all ${tab === 'otp' ? 'bg-white text-[#111111]' : 'text-[#9CA3AF] hover:text-white'}`}
          >
            <Phone className="inline h-3.5 w-3.5 mr-1.5" />Mobile OTP
          </button>
          <button
            type="button"
            onClick={() => { setTab('email'); clearError(); }}
            className={`flex-1 text-xs font-semibold py-2 rounded-lg transition-all ${tab === 'email' ? 'bg-white text-[#111111]' : 'text-[#9CA3AF] hover:text-white'}`}
          >
            <Mail className="inline h-3.5 w-3.5 mr-1.5" />Email & Password
          </button>
        </div>

        {/* ---- OTP TAB ---- */}
        {tab === 'otp' && otpStep === 'phone' && (
          <form onSubmit={handleRequestOtp} className="space-y-5">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#9CA3AF]">Mobile Number</label>
              <div className="flex items-center bg-[#0E0F11] border border-[#27282A] rounded-xl focus-within:border-[#3B82F6] focus-within:ring-1 focus-within:ring-[#3B82F6] transition-all overflow-hidden">
                <span className="pl-3.5 pr-2.5 text-[#9CA3AF] text-sm font-medium border-r border-[#27282A] py-3 select-none">+91</span>
                <input
                  type="text"
                  maxLength={10}
                  placeholder="10-digit number"
                  value={mobile}
                  onChange={(e) => { setMobile(e.target.value.replace(/\D/g,'').slice(0,10)); clearError(); }}
                  className="w-full px-3 py-3 bg-transparent outline-none text-white text-sm"
                  disabled={loading}
                  required
                />
              </div>
            </div>
            {error && <p className="text-xs text-red-500 bg-red-500/10 border border-red-500/20 px-3.5 py-2.5 rounded-xl">{error}</p>}
            <button type="submit" disabled={loading || mobile.replace(/\D/g,'').length < 10}
              className="w-full py-3 px-4 bg-white hover:bg-gray-100 text-[#111111] font-semibold text-sm rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">
              {loading ? 'Sending OTP…' : <><span>Send OTP</span><ArrowRight className="h-4 w-4" /></>}
            </button>
            {isDev && (
              <div className="border-t border-[#27282A] pt-5">
                <p className="text-[11px] font-bold text-[#6B7280] uppercase tracking-wider mb-3">Quick Login — Dev</p>
                <div className="space-y-2">
                  {DEV_QUICK_LOGINS.map((u) => {
                    const Icon = u.icon;
                    return (
                      <button key={u.label} type="button" onClick={() => fillMobile(u.mobile)}
                        className="w-full flex items-center justify-between p-3 rounded-xl bg-[#202123] border border-[#27282A] hover:bg-[#2A2B2D] transition-colors text-left">
                        <div className="flex items-center gap-2.5">
                          <div className="p-1.5 rounded-lg" style={{ background: `${u.color}1a`, color: u.color }}><Icon className="h-4 w-4" /></div>
                          <div>
                            <p className="text-xs font-semibold text-white">{u.label}</p>
                            <p className="text-[10px] text-[#9CA3AF]">{u.hint}</p>
                          </div>
                        </div>
                        <span className="text-[10px] text-[#9CA3AF] bg-[#0E0F11] px-2 py-0.5 rounded border border-[#27282A]">Fill</span>
                      </button>
                    );
                  })}
                </div>
                <p className="text-[10px] text-[#6B7280] mt-3 text-center">OTP printed to <code className="text-[#9CA3AF]">docker compose logs backend</code></p>
              </div>
            )}
          </form>
        )}

        {tab === 'otp' && otpStep === 'code' && (
          <form onSubmit={handleVerifyOtp} className="space-y-5">
            <div className="space-y-1.5">
              <div className="flex justify-between items-center">
                <label className="text-xs font-semibold text-[#9CA3AF]">Verification Code</label>
                <button type="button" onClick={() => { setOtpStep('phone'); setOtpCode(''); clearError(); }}
                  className="text-xs text-[#3B82F6] hover:underline">Change Number</button>
              </div>
              <OtpInput value={otpCode} onChange={setOtpCode} disabled={loading} />
              <p className="text-[11px] text-[#9CA3AF] text-center mt-1">
                OTP sent to <span className="font-semibold text-white">+91 {mobile}</span>
              </p>
            </div>
            {error && <p className="text-xs text-red-500 bg-red-500/10 border border-red-500/20 px-3.5 py-2.5 rounded-xl">{error}</p>}
            <button type="submit" disabled={loading || otpCode.replace(/\D/g,'').length !== 6}
              className="w-full py-3 px-4 bg-white hover:bg-gray-100 text-[#111111] font-semibold text-sm rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">
              {loading ? 'Verifying…' : <><span>Verify & Continue</span><ArrowRight className="h-4 w-4" /></>}
            </button>
          </form>
        )}

        {/* ---- EMAIL/PASS TAB ---- */}
        {tab === 'email' && (
          <form onSubmit={handleEmailLogin} className="space-y-5">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#9CA3AF]">Email Address</label>
              <div className="flex items-center bg-[#0E0F11] border border-[#27282A] rounded-xl focus-within:border-[#3B82F6] focus-within:ring-1 focus-within:ring-[#3B82F6] transition-all overflow-hidden">
                <Mail className="ml-3.5 h-4 w-4 text-[#9CA3AF] shrink-0" />
                <input type="email" placeholder="you@example.com" value={email}
                  onChange={(e) => { setEmail(e.target.value); clearError(); }}
                  className="w-full px-3 py-3 bg-transparent outline-none text-white text-sm"
                  disabled={loading} required />
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#9CA3AF]">Password</label>
              <div className="flex items-center bg-[#0E0F11] border border-[#27282A] rounded-xl focus-within:border-[#3B82F6] focus-within:ring-1 focus-within:ring-[#3B82F6] transition-all overflow-hidden">
                <Lock className="ml-3.5 h-4 w-4 text-[#9CA3AF] shrink-0" />
                <input type={showPass ? 'text' : 'password'} placeholder="••••••••" value={password}
                  onChange={(e) => { setPassword(e.target.value); clearError(); }}
                  className="w-full px-3 py-3 bg-transparent outline-none text-white text-sm"
                  disabled={loading} required />
                <button type="button" onClick={() => setShowPass(!showPass)}
                  className="mr-3 text-[#9CA3AF] hover:text-white transition-colors">
                  {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            {error && <p className="text-xs text-red-500 bg-red-500/10 border border-red-500/20 px-3.5 py-2.5 rounded-xl">{error}</p>}
            <button type="submit" disabled={loading || !email.trim() || !password}
              className="w-full py-3 px-4 bg-white hover:bg-gray-100 text-[#111111] font-semibold text-sm rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">
              {loading ? 'Signing in…' : <><span>Sign In</span><ArrowRight className="h-4 w-4" /></>}
            </button>

            {isDev && (
              <div className="border-t border-[#27282A] pt-5">
                <p className="text-[11px] font-bold text-[#6B7280] uppercase tracking-wider mb-3">Quick Login — Dev</p>
                <div className="space-y-2">
                  {DEV_QUICK_LOGINS.map((u) => {
                    const Icon = u.icon;
                    return (
                      <button key={u.label} type="button" onClick={() => fillEmail(u.email)}
                        className="w-full flex items-center justify-between p-3 rounded-xl bg-[#202123] border border-[#27282A] hover:bg-[#2A2B2D] transition-colors text-left">
                        <div className="flex items-center gap-2.5">
                          <div className="p-1.5 rounded-lg" style={{ background: `${u.color}1a`, color: u.color }}><Icon className="h-4 w-4" /></div>
                          <div>
                            <p className="text-xs font-semibold text-white">{u.label}</p>
                            <p className="text-[10px] text-[#9CA3AF]">{u.email}</p>
                          </div>
                        </div>
                        <span className="text-[10px] text-[#9CA3AF] bg-[#0E0F11] px-2 py-0.5 rounded border border-[#27282A]">Fill</span>
                      </button>
                    );
                  })}
                </div>
                <p className="text-[10px] text-[#6B7280] mt-3 text-center">Password: <code className="text-[#9CA3AF]">Password123!</code></p>
              </div>
            )}
          </form>
        )}

      </div>
    </div>
  );
};

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Phone, KeyRound, ArrowRight, ShieldCheck, Building2 } from 'lucide-react';

export const Login = () => {
  const { loginWithPhone, addToast } = useApp();
  const navigate = useNavigate();

  const [phoneNumber, setPhoneNumber] = useState('');
  const [otpArray, setOtpArray] = useState(['', '', '', '', '', '']);
  const [step, setStep] = useState('phone'); // 'phone' or 'otp'
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleOtpChange = (value, index) => {
    const cleanVal = value.replace(/\D/g, '');
    const newOtp = [...otpArray];
    newOtp[index] = cleanVal.substring(cleanVal.length - 1);
    setOtpArray(newOtp);

    // Auto-focus next input
    if (cleanVal && index < 5) {
      document.getElementById(`otp-${index + 1}`)?.focus();
    }
  };

  const handleOtpKeyDown = (e, index) => {
    if (e.key === 'Backspace') {
      if (otpArray[index] === '' && index > 0) {
        const newOtp = [...otpArray];
        newOtp[index - 1] = '';
        setOtpArray(newOtp);
        document.getElementById(`otp-${index - 1}`)?.focus();
      } else {
        const newOtp = [...otpArray];
        newOtp[index] = '';
        setOtpArray(newOtp);
      }
    }
  };

  const handleOtpPaste = (e) => {
    e.preventDefault();
    const pasteData = e.clipboardData.getData('text').replace(/\D/g, '').substring(0, 6);
    if (pasteData.length > 0) {
      const newOtp = [...otpArray];
      for (let i = 0; i < pasteData.length; i++) {
        newOtp[i] = pasteData[i];
      }
      setOtpArray(newOtp);
      const nextFocusIndex = Math.min(5, pasteData.length);
      document.getElementById(`otp-${nextFocusIndex}`)?.focus();
    }
  };

  const handlePhoneSubmit = (e) => {
    e.preventDefault();
    setError('');

    const cleanPhone = phoneNumber.replace(/\D/g, '');
    if (cleanPhone.length !== 10) {
      setError('Please enter a valid 10-digit mobile number.');
      return;
    }

    if (cleanPhone !== '9561311757' && cleanPhone !== '7588611478') {
      setError('Unrecognized number. Use 9561311757 (Agency) or 7588611478 (Business).');
      return;
    }

    setIsLoading(true);
    // Simulate API delay for sending OTP
    setTimeout(() => {
      setIsLoading(false);
      setStep('otp');
      addToast('Mock OTP sent successfully! (Use 123456)', 'info');
      // Auto-focus first digit field
      setTimeout(() => {
        document.getElementById('otp-0')?.focus();
      }, 50);
    }, 800);
  };

  const handleOtpSubmit = (e) => {
    e.preventDefault();
    setError('');

    const otpValue = otpArray.join('');
    if (otpValue !== '123456') {
      setError('Invalid OTP code. Please enter 123456.');
      return;
    }

    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      const cleanPhone = phoneNumber.replace(/\D/g, '');
      const role = cleanPhone === '9561311757' ? 'super_admin' : 'business_admin';

      loginWithPhone(cleanPhone, role);

      if (role === 'super_admin') {
        navigate('/super-admin/dashboard');
      } else {
        navigate('/business/dashboard');
      }
    }, 800);
  };

  return (
    <div className="min-h-screen bg-[#0E0F11] flex items-center justify-center p-6 font-sans relative overflow-hidden">
      {/* Background blobs for premium glassmorphism aesthetic */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-[#3B82F6]/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-[#8B5CF6]/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="w-full max-w-md bg-[#18191B] border border-[#27282A] rounded-2xl p-8 shadow-2xl relative z-10">

        {/* Brand/Logo */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="h-12 w-12 bg-white text-[#111111] font-extrabold flex items-center justify-center rounded-xl text-[24px] mb-3 shadow-lg">
            O
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">Welcome to Onella SaaS</h2>
          <p className="text-xs text-[#9CA3AF] mt-1">Sign in to manage your shops & messages</p>
        </div>

        {step === 'phone' ? (
          <form onSubmit={handlePhoneSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#9CA3AF]">Mobile Number</label>
              <div className="flex items-center bg-[#0E0F11] border border-[#27282A] rounded-xl focus-within:border-[#3B82F6] focus-within:ring-1 focus-within:ring-[#3B82F6] transition-all overflow-hidden">
                <span className="pl-3.5 pr-2.5 text-[#9CA3AF] text-sm font-medium border-r border-[#27282A] py-3 select-none">
                  +91
                </span>
                <input
                  type="text"
                  maxLength="10"
                  placeholder="Enter 10-digit number"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value.replace(/\D/g, '').substring(0, 10))}
                  className="w-full px-3 py-3 bg-transparent outline-none text-white text-sm"
                  disabled={isLoading}
                  required
                />
              </div>
            </div>

            {error && (
              <p className="text-xs text-red-500 bg-red-500/10 border border-red-500/20 px-3.5 py-2.5 rounded-xl font-medium">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isLoading || phoneNumber.length !== 10}
              className="w-full py-3 px-4 bg-white hover:bg-gray-100 text-[#111111] font-semibold text-sm rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? 'Sending OTP...' : 'Send OTP'}
              {!isLoading && <ArrowRight className="h-4 w-4" />}
            </button>

            {/* Quick Login Assist panel */}
            <div className="border-t border-[#27282A] pt-5 mt-6">
              <p className="text-[11px] font-bold text-[#6B7280] uppercase tracking-wider mb-3">Quick Login credentials</p>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setPhoneNumber('9561311757')}
                  className="w-full flex items-center justify-between p-3 rounded-xl bg-[#202123] border border-[#27282A] hover:bg-[#2A2B2D] transition-colors text-left"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 bg-[#3B82F6]/10 rounded-lg text-[#3B82F6]">
                      <ShieldCheck className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-white">Agency Login</p>
                      <p className="text-[10px] text-[#9CA3AF]">95613 11757</p>
                    </div>
                  </div>
                  <span className="text-[10px] text-[#9CA3AF] bg-[#0E0F11] px-2 py-0.5 rounded font-medium border border-[#27282A]">Use</span>
                </button>

                <button
                  type="button"
                  onClick={() => setPhoneNumber('7588611478')}
                  className="w-full flex items-center justify-between p-3 rounded-xl bg-[#202123] border border-[#27282A] hover:bg-[#2A2B2D] transition-colors text-left"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 bg-[#8B5CF6]/10 rounded-lg text-[#8B5CF6]">
                      <Building2 className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-white">Business Login</p>
                      <p className="text-[10px] text-[#9CA3AF]">75886 11478</p>
                    </div>
                  </div>
                  <span className="text-[10px] text-[#9CA3AF] bg-[#0E0F11] px-2 py-0.5 rounded font-medium border border-[#27282A]">Use</span>
                </button>
              </div>
            </div>
          </form>
        ) : (
          <form onSubmit={handleOtpSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <div className="flex justify-between items-center">
                <label className="text-xs font-semibold text-[#9CA3AF]">Verification Code</label>
                <button
                  type="button"
                  onClick={() => setStep('phone')}
                  className="text-xs text-[#3B82F6] hover:underline"
                >
                  Change Number
                </button>
              </div>
              <div className="flex justify-between items-center gap-2 py-2">
                {otpArray.map((digit, idx) => (
                  <input
                    key={idx}
                    id={`otp-${idx}`}
                    type="text"
                    maxLength="1"
                    value={digit}
                    onChange={(e) => handleOtpChange(e.target.value, idx)}
                    onKeyDown={(e) => handleOtpKeyDown(e, idx)}
                    onPaste={handleOtpPaste}
                    className="w-12 bg-[#0E0F11] border border-[#27282A] focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] rounded-xl text-center text-lg font-bold text-white outline-none font-sans transition-all"
                    disabled={isLoading}
                    required
                  />
                ))}
              </div>
              <p className="text-[11px] text-[#9CA3AF] text-center mt-1">
                OTP sent to <span className="font-semibold text-white">+91 {phoneNumber}</span>
              </p>
            </div>

            {error && (
              <p className="text-xs text-red-500 bg-red-500/10 border border-red-500/20 px-3.5 py-2.5 rounded-xl font-medium">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isLoading || otpArray.join('').length !== 6}
              className="w-full py-3 px-4 bg-white hover:bg-gray-100 text-[#111111] font-semibold text-sm rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? 'Verifying...' : 'Verify & Continue'}
              {!isLoading && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

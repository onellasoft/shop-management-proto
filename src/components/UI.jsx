import React from 'react';
import { Loader2 } from 'lucide-react';

// Premium Button Component
export const Button = ({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  loading = false,
  icon: Icon,
  ...props
}) => {
  const baseStyle = 'inline-flex items-center justify-center font-medium rounded-custom transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:pointer-events-none';

  const variants = {
    primary: 'bg-[#111111] text-white hover:bg-black/90 active:scale-[0.98]',
    secondary: 'bg-white text-[#111111] border border-[#E5E5E5] hover:bg-[#F5F5F5] active:scale-[0.98]',
    danger: 'bg-[#DC2626] text-white hover:bg-[#DC2626]/90 active:scale-[0.98]',
    ghost: 'text-[#6B7280] hover:text-[#111111] hover:bg-[#F5F5F5] rounded-lg',
  };

  const sizes = {
    sm: 'text-xs px-1 py-1 gap-1',
    md: 'text-sm px-2 py-2 gap-2',
    lg: 'text-md px-5 py-3 gap-3',
  };

  return (
    <button
      className={`${baseStyle} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {!loading && Icon && <Icon className="h-4 w-4 shrink-0" />}
      {children}
    </button>
  );
};

// Premium Card Component
export const Card = ({ children, className = '', title, subtitle, extra }) => {
  return (
    <div className={`bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-6 ${className}`}>
      {(title || subtitle || extra) && (
        <div className="flex items-center justify-between mb-5 border-b border-[#F5F5F5] pb-4">
          <div>
            {title && <h3 className="text-[18px] font-semibold text-[#111111] tracking-tight">{title}</h3>}
            {subtitle && <p className="text-[12px] text-[#6B7280] mt-1">{subtitle}</p>}
          </div>
          {extra && <div>{extra}</div>}
        </div>
      )}
      {children}
    </div>
  );
};

// Stats Card Component
export const StatsCard = ({ title, value, change, trend = 'neutral', icon: Icon }) => {
  const isUp = trend === 'up';
  const isDown = trend === 'down';

  return (
    <div className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-5 flex items-start justify-between">
      <div className="space-y-2">
        <span className="text-[12px] font-medium text-[#6B7280] tracking-wide uppercase">{title}</span>
        <div className="flex items-baseline gap-2">
          <span className="text-[28px] font-bold text-[#111111] tracking-tight">{value}</span>
          {change && (
            <span className={`text-[12px] font-semibold ${isUp ? 'text-[#16A34A]' : isDown ? 'text-[#DC2626]' : 'text-[#6B7280]'
              }`}>
              {isUp ? '+' : ''}{change}
            </span>
          )}
        </div>
      </div>
      {Icon && (
        <div className="p-3 bg-[#FAFAFA] border border-[#E5E5E5] rounded-custom">
          <Icon className="h-5 w-5 text-[#111111]" />
        </div>
      )}
    </div>
  );
};

// Badge Component
export const Badge = ({ children, variant = 'neutral', className = '' }) => {
  const variants = {
    neutral: 'bg-[#FAFAFA] text-[#6B7280] border border-[#E5E5E5]',
    success: 'bg-[#E8F5E9] text-[#16A34A] border border-[#C8E6C9]',
    warning: 'bg-[#FFF3E0] text-[#D97706] border border-[#FFE0B2]',
    danger: 'bg-[#FFEBEE] text-[#DC2626] border border-[#FFCDD2]',
    primary: 'bg-[#111111] text-white border border-[#111111]',
  };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${variants[variant]} ${className}`}>
      {children}
    </span>
  );
};

// Input Component
export const Input = ({ label, error, className = '', ...props }) => {
  return (
    <div className="w-full space-y-1.5">
      {label && <label className="block text-[12px] font-medium text-[#111111]">{label}</label>}
      <input
        className={`w-full text-sm px-3.5 py-2.5 bg-white border ${error ? 'border-[#DC2626] focus:ring-[#DC2626]' : 'border-[#E5E5E5] focus:ring-[#111111]'
          } rounded-custom focus:outline-none focus:ring-2 focus:ring-offset-0 transition-all duration-200 ${className}`}
        {...props}
      />
      {error && <p className="text-[12px] text-[#DC2626] font-medium mt-1">{error}</p>}
    </div>
  );
};

// Search Bar Component
export const Search = ({ className = '', placeholder = 'Search...', ...props }) => {
  return (
    <div className={`relative ${className}`}>
      <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
        <svg className="h-4 w-4 text-[#6B7280]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </span>
      <input
        type="search"
        className="w-full text-sm pl-10 pr-4 py-2 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all duration-200"
        placeholder={placeholder}
        {...props}
      />
    </div>
  );
};

// Avatar Component
export const Avatar = ({ name, src, size = 'md', className = '' }) => {
  const initials = name ? name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() : '?';

  const sizes = {
    sm: 'h-8 w-8 text-xs',
    md: 'h-10 w-10 text-sm',
    lg: 'h-12 w-12 text-md',
  };

  return (
    <div className={`flex items-center justify-center rounded-full bg-[#111111] text-white font-semibold border border-white/20 select-none overflow-hidden shrink-0 ${sizes[size]} ${className}`}>
      {src ? <img src={src} alt={name} className="h-full w-full object-cover" /> : initials}
    </div>
  );
};

// Toast Alert Manager
export const Toast = ({ message, type = 'success' }) => {
  const colors = {
    success: 'border-l-[4px] border-l-[#16A34A] text-[#111111]',
    error: 'border-l-[4px] border-l-[#DC2626] text-[#111111]',
    warning: 'border-l-[4px] border-l-[#D97706] text-[#111111]',
  };

  return (
    <div className={`fixed bottom-4 right-4 z-50 flex items-center gap-3 bg-white border border-[#E5E5E5] shadow-premium px-4 py-3 rounded-custom max-w-sm animate-slide-in ${colors[type]}`}>
      <span className="text-sm font-medium">{message}</span>
    </div>
  );
};

// Skeleton Loader
export const LoadingSkeleton = ({ count = 3, className = '' }) => {
  return (
    <div className="space-y-3 w-full">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={`h-8 w-full rounded-md animate-shimmer ${className}`} />
      ))}
    </div>
  );
};

// Premium Empty State
export const EmptyState = ({ title = 'No results found', description = 'Try adjusting your filters or search term.', icon: Icon }) => {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed border-[#E5E5E5] rounded-custom bg-[#FAFAFA] space-y-4">
      {Icon ? (
        <div className="p-4 bg-white border border-[#E5E5E5] rounded-full shadow-soft text-[#6B7280]">
          <Icon className="h-8 w-8" />
        </div>
      ) : (
        <div className="text-[32px]">📦</div>
      )}
      <div className="space-y-1">
        <h4 className="text-[16px] font-semibold text-[#111111]">{title}</h4>
        <p className="text-[12px] text-[#6B7280] max-w-sm">{description}</p>
      </div>
    </div>
  );
};

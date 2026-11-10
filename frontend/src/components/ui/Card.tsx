import type { ReactNode } from 'react';
import { classNames } from '@/utils/format';

interface CardProps {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
  as?: 'div' | 'section' | 'article';
}

export function Card({ children, className, interactive = false, as = 'div' }: CardProps) {
  const Element = as;
  return (
    <Element className={classNames(interactive ? 'card-interactive' : 'card', className)}>
      {children}
    </Element>
  );
}

interface CardHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, icon, actions, className }: CardHeaderProps) {
  return (
    <div className={classNames('card-header', className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-leaf-50 text-leaf-600">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-bark-900">{title}</h3>
          {subtitle && <p className="mt-0.5 text-sm text-bark-500">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={classNames('card-body', className)}>{children}</div>;
}

export default Card;

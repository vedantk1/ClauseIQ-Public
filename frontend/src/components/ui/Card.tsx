/**
 * Enhanced Card component with improved styling
 */

import React from "react";
import { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "outlined" | "elevated";
  padding?: "none" | "sm" | "md" | "lg";
  rounded?: "none" | "sm" | "md" | "lg" | "xl";
}

const cardVariants = {
  default: "bg-bg-surface text-text-primary",
  outlined:
    "bg-bg-surface text-text-primary border border-border-muted",
  elevated:
    "bg-bg-elevated text-text-primary shadow-lg border border-border-muted",
};

const cardPadding = {
  none: "",
  sm: "p-4",
  md: "p-6",
  lg: "p-8",
};

const cardRounded = {
  none: "",
  sm: "rounded-sm",
  md: "rounded-md",
  lg: "rounded-lg",
  xl: "rounded-xl",
};

export const Card: React.FC<CardProps> = ({
  children,
  variant = "default",
  padding = "md",
  rounded = "md",
  className,
  ...props
}) => {
  return (
    <div
      className={cn(
        cardVariants[variant],
        cardPadding[padding],
        cardRounded[rounded],
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
};

export const CardHeader: React.FC<HTMLAttributes<HTMLDivElement>> = ({
  children,
  className,
  ...props
}) => (
  <div className={cn("mb-4", className)} {...props}>
    {children}
  </div>
);

export const CardTitle: React.FC<HTMLAttributes<HTMLHeadingElement>> = ({
  children,
  className,
  ...props
}) => (
  <h3
    className={cn(
      "text-lg font-semibold text-text-primary",
      className
    )}
    {...props}
  >
    {children}
  </h3>
);

export const CardContent: React.FC<HTMLAttributes<HTMLDivElement>> = ({
  children,
  className,
  ...props
}) => (
  <div
    className={cn("text-text-secondary", className)}
    {...props}
  >
    {children}
  </div>
);

export const CardFooter: React.FC<HTMLAttributes<HTMLDivElement>> = ({
  children,
  className,
  ...props
}) => (
  <div
    className={cn(
      "mt-4 pt-4 border-t border-border-muted",
      className
    )}
    {...props}
  >
    {children}
  </div>
);

// Default export for convenience
export default Card;

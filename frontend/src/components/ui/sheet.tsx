// shadcn/ui Sheet: a side panel on Radix Dialog, used for the navigation on narrow screens.
import * as SheetPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "../../lib/utils";

export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetClose = SheetPrimitive.Close;
export const SheetTitle = SheetPrimitive.Title;
export const SheetDescription = SheetPrimitive.Description;

export const SheetContent = forwardRef<
  ElementRef<typeof SheetPrimitive.Content>,
  ComponentPropsWithoutRef<typeof SheetPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <SheetPrimitive.Portal>
    <SheetPrimitive.Overlay className="fixed inset-0 z-sheet bg-scrim" />
    <SheetPrimitive.Content
      ref={ref}
      className={cn("fixed inset-y-0 left-0 z-sheet flex w-72 max-w-[85vw] flex-col shadow-md", className)}
      {...props}
    >
      {children}
      <SheetPrimitive.Close
        aria-label="Close menu"
        className="absolute right-3 top-3 inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-md"
      >
        <X className="h-5 w-5" aria-hidden="true" />
      </SheetPrimitive.Close>
    </SheetPrimitive.Content>
  </SheetPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

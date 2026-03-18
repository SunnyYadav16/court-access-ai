import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Produce a final space-separated class string by normalizing and merging Tailwind CSS class values.
 *
 * Normalizes the provided class value inputs with `clsx` and resolves Tailwind-specific conflicts with `twMerge`.
 *
 * @param inputs - Class value(s) (strings, arrays, objects, etc.) accepted by `clsx`
 * @returns The merged class string with conflicting Tailwind utilities resolved
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

import { Link } from "react-router-dom";
import { Package } from "lucide-react";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-bg px-4">
      <Package className="mb-4 h-12 w-12 text-text-muted" />
      <h1 className="font-heading text-2xl font-semibold text-text">
        Page not found
      </h1>
      <p className="mt-2 text-sm text-text-secondary">
        The page you are looking for does not exist.
      </p>
      <Link
        to="/deliveries"
        className="mt-6 rounded-lg bg-primary px-4 py-2 font-heading text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
      >
        Go to Dashboard
      </Link>
    </div>
  );
}

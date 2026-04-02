import { Routes, Route, Navigate } from "react-router-dom";
import ProtectedRoute from "@/components/ProtectedRoute";
import LoginPage from "@/pages/LoginPage";
import DeliveryListPage from "@/pages/DeliveryListPage";
import DeliveryDetailPage from "@/pages/DeliveryDetailPage";
import NotFoundPage from "@/pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route path="/" element={<Navigate to="/deliveries" replace />} />

      <Route
        path="/deliveries"
        element={
          <ProtectedRoute>
            <DeliveryListPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/deliveries/:id"
        element={
          <ProtectedRoute>
            <DeliveryDetailPage />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  setAuthCookies,
} from "@/lib/auth-cookies";
import {
  getApiErrorMessage,
} from "@/lib/error-message";
import {
  backendFetch,
  BackendApiError,
} from "@/lib/server-api";
import type {
  LoginResponse,
} from "@/types";

export async function POST(
  request: NextRequest,
) {
  try {
    const body =
      await request.json();

    const formData =
      new URLSearchParams();

    formData.append(
      "username",
      body.email,
    );

    formData.append(
      "password",
      body.password,
    );

    const data =
      await backendFetch<LoginResponse>(
        "/api/v1/auth/login",
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/x-www-form-urlencoded",
          },
          body:
            formData.toString(),
        },
      );

    const user =
      await backendFetch(
        "/api/v1/auth/me",
        {
          headers: {
            Authorization:
              `Bearer ${data.access_token}`,
          },
        },
      );

    const response =
      NextResponse.json({
        user,
        access_token:
          data.access_token,
        message:
          "Login successful",
      });

    setAuthCookies(response, {
      accessToken:
        data.access_token,
      refreshToken:
        data.refresh_token,
    });

    return response;
  } catch (error) {
    if (
      error instanceof
      BackendApiError
    ) {
      const detail =
        getApiErrorMessage(
          error.data,
          "Login failed",
        );

      return NextResponse.json(
        { detail },
        {
          status:
            error.status,
        },
      );
    }

    return NextResponse.json(
      {
        detail:
          "Internal server error",
      },
      {
        status: 500,
      },
    );
  }
}
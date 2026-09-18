// API service for user interactions (notes and flags)
import config from "@/config/config";
import { LOCAL_API_HEADERS } from "@/lib/api";

export interface Note {
  id: string;
  text: string;
  created_at: string;
}

export interface UserInteraction {
  clause_id: string;
  workspace_id: string;
  notes: Note[];
  is_flagged: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserInteractionRequest {
  note?: string;
  is_flagged: boolean;
}

export interface NoteRequest {
  text: string;
}

export interface UserInteractionsResponse {
  interactions: Record<string, UserInteraction>;
}

class UserInteractionService {
  private async getLocalHeaders(): Promise<HeadersInit> {
    return {
      "Content-Type": "application/json",
      ...LOCAL_API_HEADERS,
    };
  }

  /**
   * Get all user interactions for a document
   */
  async getUserInteractions(
    documentId: string,
  ): Promise<Record<string, UserInteraction>> {

    if (!documentId) {
      console.error("❌ [DEBUG] No documentId provided");
      throw new Error("Document ID is required");
    }

    try {
      const url = `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions`;

      const headers = await this.getLocalHeaders();

      const response = await fetch(url, {
        method: "GET",
        headers,
      });


      if (!response.ok) {
        const errorText = await response.text();
        console.error("❌ [DEBUG] Error response body:");
        throw new Error(
          `Failed to fetch user interactions: ${response.status} ${response.statusText} - ${errorText}`,
        );
      }

      const data = await response.json();
      return data.data?.interactions || {};
    } catch (error) {
      console.error("❌ [DEBUG] Error fetching user interactions:");
      throw error;
    }
  }

  /**
   * Save or update user interaction for a specific clause
   */
  async saveUserInteraction(
    documentId: string,
    clauseId: string,
    interaction: UserInteractionRequest,
  ): Promise<UserInteraction> {
    try {
      const response = await fetch(
        `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions/${clauseId}`,
        {
          method: "PUT",
          headers: await this.getLocalHeaders(),
          body: JSON.stringify(interaction),
        },
      );

      if (!response.ok) {
        throw new Error(
          `Failed to save user interaction: ${response.statusText}`,
        );
      }

      const data = await response.json();
      return data.data?.interaction;
    } catch (error) {
      console.error("Error saving user interaction:");
      throw error;
    }
  }

  /**
   * Delete user interaction for a specific clause
   */
  async deleteUserInteraction(
    documentId: string,
    clauseId: string,
  ): Promise<void> {
    try {
      const response = await fetch(
        `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions/${clauseId}`,
        {
          method: "DELETE",
          headers: await this.getLocalHeaders(),
        },
      );

      if (!response.ok) {
        throw new Error(
          `Failed to delete user interaction: ${response.statusText}`,
        );
      }
    } catch (error) {
      console.error("Error deleting user interaction:");
      throw error;
    }
  }

  /**
   * Add a new note to a clause
   */
  async addNote(
    documentId: string,
    clauseId: string,
    text: string,
  ): Promise<Note> {
    try {
      const response = await fetch(
        `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions/${clauseId}/notes`,
        {
          method: "POST",
          headers: await this.getLocalHeaders(),
          body: JSON.stringify({ text }),
        },
      );

      if (!response.ok) {
        throw new Error(`Failed to add note: ${response.statusText}`);
      }

      const data = await response.json();
      return data.data?.note;
    } catch (error) {
      console.error("Error adding note:");
      throw error;
    }
  }

  /**
   * Update an existing note
   */
  async updateNote(
    documentId: string,
    clauseId: string,
    noteId: string,
    text: string,
  ): Promise<Note> {

    try {
      const url = `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions/${clauseId}/notes/${noteId}`;
      const headers = await this.getLocalHeaders();
      const body = JSON.stringify({ text });


      const response = await fetch(url, {
        method: "PUT",
        headers,
        body,
      });


      if (!response.ok) {
        const errorText = await response.text();
        console.error("✏️ [ERROR] Update note failed:");
        throw new Error(
          `Failed to update note: ${response.status} ${response.statusText} - ${errorText}`,
        );
      }

      const data = await response.json();

      // Check if the API returned an error even with 200 status
      if (!data.success) {
        console.error("✏️ [ERROR] API returned success=false:");
        throw new Error(
          `API returned error: ${data.error?.message || "Unknown error"}`,
        );
      }

      const note = data.data?.note;

      return note;
    } catch (error) {
      console.error("✏️ [ERROR] Error updating note:");
      throw error;
    }
  }

  /**
   * Delete a specific note
   */
  async deleteNote(
    documentId: string,
    clauseId: string,
    noteId: string,
  ): Promise<void> {
    try {
      const response = await fetch(
        `${config.apiUrl}/api/v1/analysis/documents/${documentId}/interactions/${clauseId}/notes/${noteId}`,
        {
          method: "DELETE",
          headers: await this.getLocalHeaders(),
        },
      );

      if (!response.ok) {
        throw new Error(`Failed to delete note: ${response.statusText}`);
      }
    } catch (error) {
      console.error("Error deleting note:");
      throw error;
    }
  }

  /**
   * Helper method to save only a note (backward compatibility)
   */
  async saveNote(
    documentId: string,
    clauseId: string,
    note: string,
  ): Promise<UserInteraction> {
    return this.saveUserInteraction(documentId, clauseId, {
      note,
      is_flagged: false, // Will be overridden by backend if already flagged
    });
  }
}

export const userInteractionService = new UserInteractionService();

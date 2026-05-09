#!/usr/bin/env python3
"""
Lexmount Login Session & Context Management Script

Usage:
  1. Create and save login state (mode auto-selected)
     uv run scripts/manage_login_session.py create --save-context

  2. Reuse saved login state (mode auto-selected)
     uv run scripts/manage_login_session.py create --context-id <context_id>

  3. List all contexts (saved login states)
     uv run scripts/manage_login_session.py list-contexts

  4. Get context details
     uv run scripts/manage_login_session.py get-context --context-id <context_id>

  5. Delete contexts
     uv run scripts/manage_login_session.py delete-contexts [--context-id <id> | --all]

  6. List all sessions (optional)
     uv run scripts/manage_login_session.py list-sessions

  7. Close session (optional)
     uv run scripts/manage_login_session.py close-session --session-id <session_id>

Configuration Requirements:
  Add the following to .env file in project root:
  LEXMOUNT_API_KEY=your_api_key
  LEXMOUNT_PROJECT_ID=your_project_id
  LEXMOUNT_BASE_URL=https://api.lexmount.cn
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
env_file = project_root / ".env"
load_dotenv(dotenv_path=env_file, override=True)

# Setup logger with project's unified logging utility
from browseruse_bench.utils import setup_logger

logger = setup_logger("manage_login_session")

try:
    from lexmount import Lexmount, ContextNotFoundError, APIError
except ImportError:
    logger.error("[FAILED] lexmount package not found, please install: pip install lexmount")
    sys.exit(1)


def validate_env():
    """Validate environment variable configuration"""
    required_vars = ['LEXMOUNT_API_KEY', 'LEXMOUNT_PROJECT_ID']
    missing_vars = []

    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        logger.error(f"[FAILED] Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please configure in .env file:")
        logger.error("  LEXMOUNT_API_KEY=your_api_key")
        logger.error("  LEXMOUNT_PROJECT_ID=your_project_id")
        logger.error("  LEXMOUNT_BASE_URL=https://api.lexmount.cn (optional)")
        sys.exit(1)

    return {
        'api_key': os.environ['LEXMOUNT_API_KEY'],
        'project_id': os.environ['LEXMOUNT_PROJECT_ID'],
        'base_url': os.environ.get('LEXMOUNT_BASE_URL'),
    }


def create_session(mode=None, save_context=False, context_id=None, context_metadata=None):
    """Create browser session with optional context support
    
    Args:
        mode: Browser mode ('uc' or 'normal'), auto-selected if using context
        save_context: Whether to save context (login state) after session
        context_id: Existing context ID to use (for reusing login state)
        context_metadata: Metadata to attach to the context
    """
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info("Create Lexmount Browser Session")
    logger.info(f"{'='*80}")

    # Initialize Lexmount Client
    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    # Prepare context configuration
    context_config = None
    created_context_id = None
    
    # Auto-select mode when using context
    if (save_context or context_id) and mode is None:
        mode = 'normal'  # Use normal mode for context operations
    elif mode is None:
        mode = 'uc'  # Default to uc for manual login
    
    if context_id:
        # Use existing context
        logger.info(f"[INFO] Using existing context: {context_id}")
        context_config = {"id": context_id, "mode": "read_write"}
    elif save_context:
        # Create new context
        logger.info("[INFO] Creating new context to save login state...")
        try:
            metadata = context_metadata or {}
            metadata['created_by'] = 'manage_login_session'
            
            context = lm.contexts.create(metadata=metadata)
            created_context_id = context.id
            context_config = {"id": context.id, "mode": "read_write"}
            logger.info(f"[SUCCESS] Context created: {context.id}")
        except Exception as e:
            logger.error(f"[FAILED] Failed to create context: {e}")
            sys.exit(1)

    # Create Session
    logger.info("[INFO] Creating session...")
    if context_config:
        logger.info(f"   Context: {context_config['id']}")
        logger.info("   Note: Login state will be preserved in context")
    else:
        logger.info(f"   Mode: {mode.upper()}")
        if mode == 'uc':
            logger.info("   Note: UC mode - For first time login")
        else:
            logger.info("   Note: Normal mode")

    try:
        session_kwargs = {'browser_mode': mode}
        if context_config:
            session_kwargs['context'] = context_config
            
        session = lm.sessions.create(**session_kwargs)
        logger.info("[SUCCESS] Session created.")
        logger.info("[INFO] Session Info:")
        logger.info(f"   Session ID: {session.id}")
        logger.info(f"   Connect URL: {session.connect_url}")
        if context_config:
            logger.info(f"   Context ID: {context_config['id']}")

        logger.info("[INFO] How to Access:")
        logger.info("   1. View session list in Lexmount Dashboard")
        logger.info("   2. Click 'View' button to open browser")
        logger.info("   3. Navigate to any website and complete login")

        if save_context or context_id:
            logger.info("[IMPORTANT] Context Mode:")
            logger.info("   1. Your login state will be saved to the context")
            logger.info("   2. Reuse this login state in experiments with:")
            logger.info(f"      uv run scripts/run.py --agent browser-use --context-id {context_config['id']} ...")
            if save_context:
                logger.info("   3. After login, keep the session open until you finish")
                logger.info("   4. The context will be ready after you close this session")
        elif mode == 'uc':
            logger.info("[IMPORTANT] First Login:")
            logger.info("   1. Manually login to your account in the opened browser")
            logger.info("   2. After login completes, keep the page open")
            logger.info("   3. To save login state, use --save-context:")
            logger.info("      uv run scripts/manage_login_session.py create --save-context")
        else:
            logger.info("[INFO] Session created successfully")

        logger.info("[INFO] Keep Session Alive:")
        logger.info("   This script will keep running, press Ctrl+C to close session")
        logger.info(
            "   Or close via command: uv run scripts/manage_login_session.py close-session --session-id %s",
            session.id,
        )

        # Keep script running until user interrupts
        try:
            input("\nPress Enter to close session and exit...")
        except KeyboardInterrupt:
            logger.info("[INFO] Received interrupt signal...")

        # Close session
        logger.info("[INFO] Closing session...")
        session.close()
        logger.info("[SUCCESS] Session closed")
        
        if created_context_id:
            logger.info(f"[SUCCESS] Context {created_context_id} is now ready to use")
            logger.info(f"   Use it in experiments with: --context-id {created_context_id}")

    except Exception as e:
        logger.error(f"[FAILED] Failed to create session: {e}")
        # Cleanup created context if session creation failed
        if created_context_id:
            try:
                lm.contexts.delete(created_context_id)
                logger.info(f"[INFO] Cleaned up context: {created_context_id}")
            except Exception:
                pass
        sys.exit(1)


def list_sessions():
    """List all sessions"""
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info("Lexmount Browser Session List")
    logger.info(f"{'='*80}")

    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    try:
        sessions = lm.sessions.list()

        if not sessions:
            logger.info("[INFO] No active sessions")
            return

        logger.info(f"[INFO] Found {len(sessions)} active sessions:")
        for i, session in enumerate(sessions, 1):
            logger.info(f"{i}. Session ID: {session.id}")
            logger.info(f"   Mode: {getattr(session, 'browser_mode', 'unknown')}")
            logger.info(f"   Status: {getattr(session, 'status', 'unknown')}")
            logger.info(f"   Connect URL: {session.connect_url}")

    except Exception as e:
        logger.error(f"[FAILED] Failed to get session list: {e}")
        sys.exit(1)


def close_session(session_id):
    """Close specified session"""
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info("Close Lexmount Browser Session")
    logger.info(f"{'='*80}")

    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    try:
        logger.info(f"[INFO] Closing session: {session_id}")
        # Note: Need to get session object first
        # Assuming Lexmount SDK supports getting session by ID
        session = lm.sessions.get(session_id)
        session.close()
        logger.info("[SUCCESS] Session closed")

    except Exception as e:
        logger.error(f"[FAILED] Failed to close session: {e}")
        logger.error("   Hint: Session might remain closed or not exist")
        sys.exit(1)


def list_contexts():
    """List all contexts (saved login states)"""
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info("Lexmount Context List (Saved Login States)")
    logger.info(f"{'='*80}")

    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    try:
        contexts = lm.contexts.list()

        if not contexts:
            logger.info("[INFO] No contexts found")
            return

        logger.info(f"[INFO] Found {len(contexts)} context(s):")
        for i, ctx in enumerate(contexts, 1):
            status_icon = "🔒" if ctx.is_locked() else "✅"
            logger.info(f"\n{i}. {status_icon} Context ID: {ctx.id}")
            logger.info(f"   Status: {ctx.status}")
            if ctx.is_locked():
                logger.info("   Note: Currently locked (in use by a session)")
            if hasattr(ctx, 'metadata') and ctx.metadata:
                logger.info(f"   Metadata: {ctx.metadata}")
            if ctx.created_at:
                logger.info(f"   Created: {ctx.created_at}")
            if ctx.updated_at:
                logger.info(f"   Updated: {ctx.updated_at}")

    except APIError as e:
        logger.error(f"[FAILED] Failed to list contexts: {e}")
        logger.error("   (Service may be temporarily unavailable, please retry)")
        sys.exit(1)


def get_context_details(context_id):
    """Get detailed information about a specific context"""
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info(f"Context Details: {context_id}")
    logger.info(f"{'='*80}")

    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    try:
        ctx = lm.contexts.get(context_id)
        logger.info(f"[SUCCESS] Context found")
        logger.info(f"   Context ID: {ctx.id}")
        logger.info(f"   Status: {ctx.status}")
        if ctx.is_locked():
            logger.info("   🔒 Locked (currently in use)")
        else:
            logger.info("   ✅ Available")
        if hasattr(ctx, 'metadata') and ctx.metadata:
            logger.info(f"   Metadata: {ctx.metadata}")
        if ctx.created_at:
            logger.info(f"   Created: {ctx.created_at}")
        if ctx.updated_at:
            logger.info(f"   Updated: {ctx.updated_at}")
        
        logger.info("\n[INFO] How to use this context:")
        logger.info(f"   uv run scripts/run.py --agent browser-use --context-id {context_id} ...")

    except ContextNotFoundError:
        logger.error(f"[FAILED] Context not found: {context_id}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Failed to get context details: {e}")
        sys.exit(1)


def delete_contexts(context_id=None, delete_all=False):
    """Delete context(s)"""
    config = validate_env()

    logger.info(f"\n{'='*80}")
    logger.info("Delete Lexmount Context(s)")
    logger.info(f"{'='*80}")

    lm_kwargs = {
        'api_key': config['api_key'],
        'project_id': config['project_id']
    }
    if config['base_url']:
        lm_kwargs['base_url'] = config['base_url']

    lm = Lexmount(**lm_kwargs)

    try:
        if delete_all:
            contexts = lm.contexts.list()
            if not contexts:
                logger.info("[INFO] No contexts to delete")
                return
            
            logger.info(f"[INFO] Found {len(contexts)} context(s). Deleting unlocked ones...")
            deleted = 0
            skipped_locked = 0
            failed = 0
            
            for ctx in contexts:
                if ctx.is_locked():
                    logger.info(f"   ⏭ Skipped (locked): {ctx.id}")
                    skipped_locked += 1
                    continue
                try:
                    lm.contexts.delete(ctx.id)
                    logger.info(f"   ✓ Deleted: {ctx.id}")
                    deleted += 1
                except Exception as e:
                    logger.error(f"   ✗ Failed to delete {ctx.id}: {e}")
                    failed += 1
            
            logger.info(f"\n[SUCCESS] Done: {deleted} deleted, {skipped_locked} skipped (locked), {failed} failed")
        
        elif context_id:
            logger.info(f"[INFO] Deleting context: {context_id}")
            try:
                ctx = lm.contexts.get(context_id)
                if ctx.is_locked():
                    logger.error(f"[FAILED] Context is locked (currently in use): {context_id}")
                    logger.error("   Please close the session using this context first")
                    sys.exit(1)
                
                lm.contexts.delete(context_id)
                logger.info("[SUCCESS] Context deleted")
            except ContextNotFoundError:
                logger.error(f"[FAILED] Context not found: {context_id}")
                sys.exit(1)
        else:
            logger.error("[FAILED] Please specify --context-id or --all")
            sys.exit(1)

    except Exception as e:
        logger.error(f"[FAILED] Failed to delete context(s): {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Lexmount Login Session & Context Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  # Create and save login state (mode auto-selected)
  uv run scripts/manage_login_session.py create --save-context

  # Reuse saved login state (mode auto-selected)
  uv run scripts/manage_login_session.py create --context-id <context_id>

  # Manual login without context (uses uc mode by default)
  uv run scripts/manage_login_session.py create

  # List all sessions
  uv run scripts/manage_login_session.py list-sessions

  # Close specific session
  uv run scripts/manage_login_session.py close-session --session-id <session_id>

  # List all contexts (saved login states)
  uv run scripts/manage_login_session.py list-contexts

  # Get context details
  uv run scripts/manage_login_session.py get-context --context-id <context_id>

  # Delete specific context
  uv run scripts/manage_login_session.py delete-contexts --context-id <context_id>

  # Delete all unlocked contexts
  uv run scripts/manage_login_session.py delete-contexts --all
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command')

    # create command
    create_parser = subparsers.add_parser('create', help='Create browser session')
    create_parser.add_argument(
        '--mode',
        choices=['uc', 'normal'],
        default=None,
        help='Browser mode (optional: auto-selected when using context)'
    )
    create_parser.add_argument(
        '--save-context',
        action='store_true',
        help='Create and save context (login state) for later reuse'
    )
    create_parser.add_argument(
        '--context-id',
        help='Use existing context ID (reuse saved login state)'
    )

    # list-sessions command
    subparsers.add_parser('list-sessions', help='List all active sessions')

    # close-session command
    close_session_parser = subparsers.add_parser('close-session', help='Close specified session')
    close_session_parser.add_argument('--session-id', required=True, help='Session ID')

    # list-contexts command
    subparsers.add_parser('list-contexts', help='List all contexts (saved login states)')

    # get-context command
    get_context_parser = subparsers.add_parser('get-context', help='Get context details')
    get_context_parser.add_argument('--context-id', required=True, help='Context ID')

    # delete-contexts command
    delete_contexts_parser = subparsers.add_parser('delete-contexts', help='Delete context(s)')
    delete_contexts_parser.add_argument('--context-id', help='Context ID to delete')
    delete_contexts_parser.add_argument('--all', action='store_true', help='Delete all unlocked contexts')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == 'create':
        # Validate conflicting options
        if args.save_context and args.context_id:
            logger.error("[FAILED] Cannot use both --save-context and --context-id")
            sys.exit(1)
        
        create_session(
            mode=args.mode,
            save_context=args.save_context,
            context_id=args.context_id
        )
    elif args.command == 'list-sessions':
        list_sessions()
    elif args.command == 'close-session':
        close_session(args.session_id)
    elif args.command == 'list-contexts':
        list_contexts()
    elif args.command == 'get-context':
        get_context_details(args.context_id)
    elif args.command == 'delete-contexts':
        if not args.context_id and not args.all:
            logger.error("[FAILED] Please specify --context-id or --all")
            sys.exit(1)
        delete_contexts(context_id=args.context_id, delete_all=args.all)


if __name__ == '__main__':
    main()
